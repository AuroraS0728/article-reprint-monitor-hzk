from __future__ import annotations

from datetime import datetime
from typing import cast
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.reposts.models import ContentRelation, RepostRecord

from .authentication import SourceTokenAuthentication
from .models import OwnedChannel, ReadingMetricObservation, SourceIngestToken
from .reading_export_services import build_owned_reading_workbook
from .reading_metrics import fetch_reading_metrics
from .serializers import ReadingMetricObservationSubmitSerializer


def _owned_reading_records(*, as_of: datetime | None = None) -> list[RepostRecord]:
    cutoff = as_of or timezone.now()
    return list(
        RepostRecord.objects.filter(
            is_valid=True,
            content_relation=ContentRelation.OWNED,
            created_at__lte=cutoff,
            article__created_at__lte=cutoff,
        )
        .select_related("article", "owned_channel")
        .order_by("-first_found_at", "-id")[:500]
    )


def _reading_publication_payload(record: RepostRecord) -> dict[str, object]:
    latest = record.reading_metric_observations.order_by("-observed_at", "-id").first()
    return {
        "id": record.id,
        "article_id": record.article_id,
        "article_title": record.article.title,
        "channel_id": record.owned_channel_id,
        "channel_name": record.owned_channel.name if record.owned_channel else "",
        "url": record.canonical_url or record.normalized_url,
        "published_at": record.result_published_at,
        "last_observed_at": latest.observed_at if latest else None,
        "last_reading_count": latest.reading_count if latest else None,
        "last_status": latest.status if latest else "",
    }


class OwnedChannelReadingView(APIView):
    """A safe reading-metric boundary: configuration and owned publications only.

    No reading provider is called until a real approved provider is integrated.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        channels = OwnedChannel.objects.filter(is_active=True).order_by("code")
        records = _owned_reading_records()
        reading_metrics, provider_status = fetch_reading_metrics(records)
        publications = []
        for record in records:
            metric = reading_metrics.get(record.id)
            publications.append(
                {
                    "id": record.id,
                    "article_id": record.article_id,
                    "article_title": record.article.title,
                    "channel_name": (record.owned_channel.name if record.owned_channel else ""),
                    "url": record.canonical_url or record.normalized_url,
                    "published_at": record.result_published_at,
                    "reading_count": metric.reading_count if metric else None,
                    "reading_status": metric.status if metric else "未查到",
                }
            )
        return ok(
            {
                "provider_status": provider_status,
                "channels": [
                    {
                        "id": channel.id,
                        "code": channel.code,
                        "name": channel.name,
                        "channel_type": channel.channel_type,
                        "notes": channel.notes,
                    }
                    for channel in channels
                ],
                "publications": publications,
            }
        )


class ReadingMetricTaskListView(APIView):
    """Return owned-channel publications that a trusted worker may observe."""

    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            return Response(
                {"success": False, "error": {"code": "INVALID_LIMIT", "message": "limit 必须是整数。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= limit <= 100:
            return Response(
                {"success": False, "error": {"code": "INVALID_LIMIT", "message": "limit 必须在 1 到 100 之间。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = cast(SourceIngestToken, request.auth)
        records = (
            RepostRecord.objects.filter(
                article__source=token.source,
                content_relation=ContentRelation.OWNED,
                is_valid=True,
            )
            .select_related("article", "owned_channel")
            .prefetch_related("reading_metric_observations")
            .order_by("-first_found_at", "id")[:limit]
        )
        return ok({"tasks": [_reading_publication_payload(record) for record in records]})


class ReadingMetricObservationSubmitView(APIView):
    """Persist trusted reading-count observations from a source worker."""

    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReadingMetricObservationSubmitSerializer

    def post(self, request: Request) -> Response:
        serializer = ReadingMetricObservationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = cast(SourceIngestToken, request.auth)
        submitted = []
        for item in cast(list[dict[str, object]], serializer.validated_data["observations"]):
            record = (
                RepostRecord.objects.filter(
                    id=cast(int, item["publication_id"]),
                    article__source=token.source,
                    content_relation=ContentRelation.OWNED,
                    is_valid=True,
                )
                .select_related("article", "owned_channel")
                .first()
            )
            if record is None:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "READING_PUBLICATION_NOT_FOUND",
                            "message": "阅读量发布记录不存在，或不属于当前 Source。",
                        },
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            observed_at = cast(datetime | None, item.get("observed_at")) or timezone.now()
            observation = ReadingMetricObservation.objects.create(
                repost_record=record,
                source=token.source,
                reading_count=cast(int | None, item.get("reading_count")),
                status=cast(str, item.get("status")),
                observed_at=observed_at,
                error_message=cast(str, item.get("error_message", "")),
            )
            submitted.append(
                {
                    "id": observation.id,
                    "publication_id": record.id,
                    "reading_count": observation.reading_count,
                    "status": observation.status,
                    "observed_at": observation.observed_at,
                }
            )
        return ok({"observations": submitted}, status.HTTP_201_CREATED)


class OwnedChannelReadingExportView(APIView):
    """Download the reading-monitor workbook without calling any provider."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> HttpResponse:
        requested_as_of = parse_datetime(request.query_params.get("as_of", ""))
        if requested_as_of and timezone.is_naive(requested_as_of):
            requested_as_of = timezone.make_aware(requested_as_of)
        if requested_as_of and requested_as_of > timezone.now():
            return HttpResponse("as_of 不能晚于当前时间", status=status.HTTP_400_BAD_REQUEST)
        content, export_as_of = build_owned_reading_workbook(export_as_of=requested_as_of)
        filename = f"自媒号阅读量_{timezone.localtime(export_as_of):%Y%m%d_%H%M}.xlsx"
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return response
