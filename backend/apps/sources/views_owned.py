from __future__ import annotations

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

from .models import OwnedChannel
from .reading_export_services import build_owned_reading_workbook


class OwnedChannelReadingView(APIView):
    """A safe reading-metric boundary: configuration and owned publications only.

    No reading provider is called until a real approved provider is integrated.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        channels = OwnedChannel.objects.filter(is_active=True).order_by("code")
        records = RepostRecord.objects.filter(
            is_valid=True,
            content_relation=ContentRelation.OWNED,
        ).select_related("article", "owned_channel")
        return ok(
            {
                "provider_status": "接口待接入",
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
                "publications": [
                    {
                        "id": record.id,
                        "article_id": record.article_id,
                        "article_title": record.article.title,
                        "channel_name": (record.owned_channel.name if record.owned_channel else ""),
                        "url": record.canonical_url or record.normalized_url,
                        "published_at": record.result_published_at,
                        "reading_count": None,
                        "reading_status": "接口待接入",
                    }
                    for record in records.order_by("-first_found_at", "-id")[:500]
                ],
            }
        )


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
