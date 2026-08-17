from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import quote

from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.articles.models import Article
from apps.audit.services import record_audit
from apps.core.permissions import CanOperate, IsAdministrator
from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.platforms.models import Platform
from apps.sources.models import SearchRunCandidate

from .export_services import GlobalExportFilters, build_global_repost_workbook
from .models import ContentRelation, RepostRecord
from .query_services import (
    RepostQueryFilters,
    channel_options,
    filtered_repost_articles,
    monitoring_status_counts,
    repost_trend,
    result_summary,
    section_options,
)
from .serializers import (
    ManualRepostCreateSerializer,
    ManualRepostStateSerializer,
    RepostRecordSerializer,
)
from .services import (
    ManualSupplementConflict,
    create_manual_supplement,
    manual_repost_before_data,
    set_manual_supplement_validity,
)


class RepostRecordListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RepostRecordSerializer

    def get(self, request: Request) -> Response:
        queryset = RepostRecord.objects.select_related("article", "platform", "manually_added_by", "invalidated_by")
        if request.query_params.get("manual") == "true":
            queryset = queryset.filter(data_source="MANUAL_SUPPLEMENT")
        return ok(RepostRecordSerializer(queryset[:200], many=True).data)


def _filters_from_request(request: Request) -> RepostQueryFilters:
    raw_has_repost = request.query_params.get("has_repost", "").lower()
    return RepostQueryFilters(
        published_from=parse_date(request.query_params.get("published_from", "")),
        published_to=parse_date(request.query_params.get("published_to", "")),
        channel=request.query_params.get("channel", "").strip(),
        section=request.query_params.get("section", "").strip(),
        monitoring_status=request.query_params.get("monitoring_status", "").strip(),
        has_repost=(True if raw_has_repost == "true" else False if raw_has_repost == "false" else None),
        site_domain=request.query_params.get("site_domain", "").strip().lower(),
        q=request.query_params.get("q", "").strip(),
    )


def _as_of(request: Request) -> datetime:
    raw_as_of = request.query_params.get("as_of", "")
    parsed = parse_datetime(raw_as_of) if raw_as_of else None
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed if parsed and parsed <= timezone.now() else timezone.now()


class RepostResultWorkspaceView(APIView):
    """Read-only, server-paginated current repost view. It never schedules a search."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        as_of = _as_of(request)
        filters = _filters_from_request(request)
        if filters.published_from is None and filters.published_to is None:
            today = timezone.localdate()
            filters = replace(filters, published_from=today - timedelta(days=6), published_to=today)
        queryset = filtered_repost_articles(filters, as_of=as_of)
        try:
            page = max(int(request.query_params.get("page", "1")), 1)
            page_size = min(max(int(request.query_params.get("page_size", "20")), 1), 100)
        except ValueError:
            return Response(
                {
                    "success": False,
                    "error": {"code": "INVALID_PAGE", "message": "分页参数无效。"},
                },
                status=400,
            )
        total = queryset.count()
        rows = list(queryset[(page - 1) * page_size : page * page_size])
        data = []
        for article in rows:
            records = list(
                article.repost_records.filter(is_valid=True, content_relation="REPOST", created_at__lte=as_of).only(
                    "site_domain", "canonical_url", "normalized_url"
                )
            )
            data.append(
                {
                    "id": article.id,
                    "published_at": article.published_at,
                    "published_date": article.published_date,
                    "channel_code": article.channel_code,
                    "channel_name": article.channel_name,
                    "section_code": article.section_code,
                    "section_name": article.section_name,
                    "title": article.title,
                    "author": article.author or article.author_department,
                    "monitoring_status": article.monitoring_status,
                    "monitor_started_at": article.monitor_started_at,
                    "monitor_until": article.monitor_until,
                    "last_searched_at": article.last_searched_at,
                    "next_search_at": article.next_search_at,
                    "search_run_count": article.search_runs.count(),
                    "repost_site_count": len({record.site_domain for record in records if record.site_domain}),
                    "repost_url_count": len({record.canonical_url or record.normalized_url for record in records}),
                }
            )
        return ok(
            {
                "as_of": as_of,
                "filters": request.query_params.dict(),
                "summary": result_summary(queryset, as_of=as_of),
                "monitoring_status_counts": monitoring_status_counts(queryset),
                "trend": repost_trend(queryset, as_of=as_of),
                "channels": channel_options(),
                "sections": section_options(),
                "results": data,
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
        )


class ArticleDiscoveredPublicationView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request, pk: int) -> Response:
        article = get_object_or_404(Article, pk=pk)
        as_of = _as_of(request)
        reposts = article.repost_records.filter(
            is_valid=True, content_relation="REPOST", created_at__lte=as_of
        ).select_related("owned_channel", "platform")
        runs = article.search_runs.order_by("-created_at", "-id")[:100]
        eligible_candidates = SearchRunCandidate.objects.filter(
            search_run__article=article,
            similarity_score__gte=settings.SEARCH_CANDIDATE_MIN_SIMILARITY,
        ).exclude(content_relation=ContentRelation.OWNED)
        latest_candidate_id = (
            eligible_candidates.filter(canonical_url=OuterRef("canonical_url"))
            .order_by("-search_run__created_at", "-id")
            .values("id")[:1]
        )
        candidates = (
            eligible_candidates.filter(pk=Subquery(latest_candidate_id))
            .select_related("search_run", "owned_channel")
            .order_by("-search_run__created_at", "-id")[:500]
        )
        return ok(
            {
                "as_of": as_of,
                "reposts": RepostRecordSerializer(reposts, many=True).data,
                "search_runs": [
                    {
                        "id": run.id,
                        "status": run.status,
                        "provider": run.provider,
                        "exact_candidate_count": run.exact_candidate_count,
                        "broad_candidate_count": run.broad_candidate_count,
                        "merged_candidate_count": run.merged_candidate_count,
                        "matched_count": run.matched_count,
                        "repost_count": run.repost_count,
                        "review_required_count": run.review_required_count,
                        "new_repost_count": run.new_repost_count,
                        "error_code": run.error_code,
                        "error_message": run.error_message,
                        "created_at": run.created_at,
                        "completed_at": run.completed_at,
                    }
                    for run in runs
                ],
                "candidates": [
                    {
                        "id": candidate.id,
                        "search_run_id": candidate.search_run_id,
                        "searched_at": candidate.search_run.created_at,
                        "title": candidate.title,
                        "site_name": candidate.site_name,
                        "site_domain": candidate.site_domain,
                        "canonical_url": candidate.canonical_url,
                        "published_at": candidate.published_at,
                        "search_phases": candidate.search_phases,
                        "disposition": candidate.disposition,
                        "similarity_score": candidate.similarity_score,
                        "content_relation": candidate.content_relation,
                        "owned_channel_id": candidate.owned_channel_id,
                        "owned_channel_name": candidate.owned_channel.name if candidate.owned_channel else None,
                        "manual_review_action": (
                            "CONFIRM_REPOST"
                            if candidate.reason_code == "MANUAL_REPOST"
                            else "CONFIRM_OWNED" if candidate.reason_code == "MANUAL_OWNED" else None
                        ),
                        "classification_reason": candidate.classification_reason or candidate.reason_code,
                    }
                    for candidate in candidates
                ],
            }
        )


class GlobalRepostExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> HttpResponse:
        start_date = parse_date(request.query_params.get("start_date", request.query_params.get("published_from", "")))
        end_date = parse_date(request.query_params.get("end_date", request.query_params.get("published_to", "")))
        raw_article_id = request.query_params.get("article_id", "")
        raw_has_repost = request.query_params.get("has_repost", "").lower()
        filters = GlobalExportFilters(
            start_date=start_date,
            end_date=end_date,
            article_id=int(raw_article_id) if raw_article_id.isdigit() else None,
            author=request.query_params.get("author", "").strip(),
            monitoring_status=request.query_params.get("monitoring_status", "").strip(),
            site_domain=request.query_params.get("site_domain", "").strip().lower(),
            has_repost=(True if raw_has_repost == "true" else False if raw_has_repost == "false" else None),
            channel=request.query_params.get("channel", "").strip(),
            section=request.query_params.get("section", "").strip(),
            q=request.query_params.get("q", "").strip(),
        )
        requested_as_of = parse_datetime(request.query_params.get("as_of", ""))
        if requested_as_of and timezone.is_naive(requested_as_of):
            requested_as_of = timezone.make_aware(requested_as_of)
        if requested_as_of and requested_as_of > timezone.now():
            return HttpResponse("as_of 不能晚于当前时间", status=status.HTTP_400_BAD_REQUEST)
        content, export_as_of = build_global_repost_workbook(filters, export_as_of=requested_as_of)
        record_audit(
            request,
            action_type="REPOST_EXPORT",
            target_type="GlobalRepostExport",
            target_id="export",
            after_data={
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "article_id": filters.article_id,
                "site_domain": filters.site_domain,
                "as_of": export_as_of.isoformat(),
            },
        )
        if start_date and end_date:
            filename = f"文章转载监测_{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
        else:
            filename = f"文章转载监测_{timezone.localtime(export_as_of):%Y%m%d_%H%M}.xlsx"
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return response


class ManualRepostCreateView(APIView):
    permission_classes = [CanOperate]
    serializer_class = ManualRepostCreateSerializer

    @extend_schema(operation_id="manual_repost_create")
    def post(self, request: Request) -> Response:
        serializer = ManualRepostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        actor = cast(User, request.user)
        try:
            record = create_manual_supplement(
                article=cast(Article, data["article"]),
                platform=cast(Platform, data["platform"]),
                repost_url=cast(str, data["repost_url"]),
                reason=cast(str, data["reason"]),
                actor=actor,
            )
        except (ManualSupplementConflict, ValueError) as error:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "MANUAL_SUPPLEMENT_INVALID",
                        "message": str(error),
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="MANUAL_REPOST_CREATE",
            target_type="RepostRecord",
            target_id=record.id,
            after_data=manual_repost_before_data(record),
        )
        return ok(RepostRecordSerializer(record).data, status.HTTP_201_CREATED)


class ManualRepostValidityView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = ManualRepostStateSerializer

    @extend_schema(operation_id="manual_repost_validity_update")
    def post(self, request: Request, pk: int, action: str) -> Response:
        serializer = ManualRepostStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = get_object_or_404(RepostRecord, pk=pk)
        before = manual_repost_before_data(record)
        valid = action == "restore"
        if action not in {"invalidate", "restore"}:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "不支持的人工补录操作。",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            record = set_manual_supplement_validity(
                record=record,
                valid=valid,
                reason=cast(str, serializer.validated_data.get("reason", "")),
                actor=cast(User, request.user),
            )
        except ValueError as error:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "MANUAL_SUPPLEMENT_INVALID",
                        "message": str(error),
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type=("MANUAL_REPOST_RESTORE" if valid else "MANUAL_REPOST_INVALIDATE"),
            target_type="RepostRecord",
            target_id=record.id,
            before_data=before,
            after_data=manual_repost_before_data(record),
        )
        return ok(RepostRecordSerializer(record).data)
