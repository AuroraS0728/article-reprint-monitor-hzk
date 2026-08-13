from __future__ import annotations

from datetime import datetime
from typing import cast

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.articles.models import Article, ArticleStatus
from apps.audit.services import record_audit
from apps.core.permissions import CanOperate, IsAdministrator
from apps.core.views import ok

from .authentication import SourceTokenAuthentication
from .models import ArticleIngestConflict, ArticleIngestConflictStatus, SearchRun, SearchRunCandidate, SourceIngestToken
from .serializers import (
    ArticleIngestConflictReviewSerializer,
    ArticleIngestConflictSerializer,
    ManualGlobalSearchSerializer,
    SearchRunCandidateSerializer,
    SourceArticleIngestSerializer,
)
from .services import approve_source_ingest_conflict, ingest_source_article, link_source_ingest_conflict
from .tasks import search_article_reposts


class SourceArticleIngestView(APIView):
    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SourceArticleIngestSerializer

    @extend_schema(operation_id="source_article_ingest", request=SourceArticleIngestSerializer)
    def post(self, request: Request) -> Response:
        serializer = SourceArticleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = cast(SourceIngestToken, request.auth)
        try:
            result = ingest_source_article(
                source=token.source,
                title=cast(str, data["title"]),
                author=cast(str, data["author"]),
                published_at=cast(datetime, data["published_at"]),
                original_url=cast(str, data["original_url"]),
                created_by=cast(User, request.user),
            )
        except ValueError as error:
            return Response(
                {"success": False, "error": {"code": "INVALID_SOURCE_ARTICLE", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if result.pending_review:
            conflict = result.conflict
            if conflict is None:
                raise RuntimeError("Source Ingest Conflict 结果缺少持久化记录。")
            if result.conflict_created:
                record_audit(
                    request,
                    action_type="SOURCE_INGEST_CONFLICT_CREATED",
                    target_type="ArticleIngestConflict",
                    target_id=conflict.id,
                    after_data={
                        "source": token.source.code,
                        "conflict_id": conflict.id,
                        "existing_article_id": conflict.existing_article_id,
                        "reason_code": result.reason_code,
                    },
                )
            return ok(
                {
                    "created": False,
                    "updated": False,
                    "pending_review": True,
                    "conflict_id": conflict.id,
                    "reason_code": "DUPLICATE_REVIEW_REQUIRED",
                },
                status.HTTP_202_ACCEPTED,
            )
        article = result.article
        if article is None:
            raise RuntimeError("Source Ingest 结果缺少 Article。")
        record_audit(
            request,
            action_type="SOURCE_ARTICLE_CREATE" if result.created else "SOURCE_ARTICLE_UPDATE",
            target_type="Article",
            target_id=article.id,
            after_data={
                "source": token.source.code,
                "article_id": article.id,
                "created": result.created,
                "updated": result.updated,
            },
        )
        return ok(
            {
                "created": result.created,
                "updated": result.updated,
                "pending_review": False,
                "article_id": article.id,
                "monitoring": article.monitoring_status == "ACTIVE",
                "monitor_until": article.monitor_until,
                "retention_until": article.retention_until,
            },
            status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class ArticleIngestConflictListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = ArticleIngestConflictSerializer

    def get(self, request: Request) -> Response:
        conflicts = ArticleIngestConflict.objects.select_related(
            "source", "existing_article", "created_article", "linked_article", "created_by", "reviewed_by"
        )
        if status_filter := request.query_params.get("status"):
            conflicts = conflicts.filter(status=status_filter)
        return ok(ArticleIngestConflictSerializer(conflicts[:200], many=True).data)


class ManualGlobalSearchView(APIView):
    """Queue an explicit one-off provider search without changing lifecycle scheduling."""

    permission_classes = [CanOperate]
    serializer_class = ManualGlobalSearchSerializer

    def get(self, request: Request) -> Response:
        article_ids = request.query_params.getlist("article_id")
        queryset = SearchRun.objects.select_related("article").order_by("-created_at", "-id")
        if article_ids:
            queryset = queryset.filter(article_id__in=article_ids)
        return ok(
            [
                {
                    "id": run.id,
                    "article_id": run.article_id,
                    "status": run.status,
                    "provider": run.provider,
                    "candidate_count": run.candidate_count,
                    "matched_count": run.matched_count,
                    "new_repost_count": run.new_repost_count,
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                    "started_at": run.started_at,
                    "completed_at": run.completed_at,
                    "created_at": run.created_at,
                }
                for run in queryset[:200]
            ]
        )

    def post(self, request: Request) -> Response:
        serializer = ManualGlobalSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article_ids = serializer.validated_data["article_ids"]
        articles = list(Article.objects.filter(id__in=article_ids).only("id", "status"))
        found_ids = {article.id for article in articles}
        missing_ids = sorted(set(article_ids) - found_ids)
        unavailable_ids = sorted(article.id for article in articles if article.status != ArticleStatus.ACTIVE)
        if missing_ids or unavailable_ids:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "MANUAL_SEARCH_ARTICLE_UNAVAILABLE",
                        "message": "手动全网检测仅支持状态为监测中的文章。",
                        "details": {"missing_article_ids": missing_ids, "unavailable_article_ids": unavailable_ids},
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        for article in articles:
            search_article_reposts.delay(article.id, manual=True)
        record_audit(
            request,
            action_type="MANUAL_GLOBAL_SEARCH_QUEUED",
            target_type="Article",
            target_id="manual-global-search",
            after_data={"article_ids": article_ids, "count": len(article_ids)},
        )
        return ok({"article_ids": article_ids, "queued_count": len(article_ids)}, status.HTTP_202_ACCEPTED)


class SearchRunCandidateListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SearchRunCandidateSerializer

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(SearchRun, pk=pk)
        candidates = SearchRunCandidate.objects.filter(search_run_id=pk)
        return ok(SearchRunCandidateSerializer(candidates, many=True).data)


class ArticleIngestConflictReviewView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = ArticleIngestConflictReviewSerializer

    def post(self, request: Request, pk: int) -> Response:
        serializer = ArticleIngestConflictReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = cast(User, request.user)
        action = cast(str, serializer.validated_data["action"])
        reason = cast(str, serializer.validated_data["reason"])
        try:
            if action == ArticleIngestConflictStatus.APPROVED_AS_NEW:
                conflict, article = approve_source_ingest_conflict(
                    conflict_id=pk,
                    approved_by=actor,
                    review_reason=reason,
                )
                record_audit(
                    request,
                    action_type="ARTICLE_DUPLICATE_APPROVED",
                    target_type="article",
                    target_id=article.id,
                    after_data={
                        "conflict_id": conflict.id,
                        "article_id": article.id,
                        "duplicate_slot": article.duplicate_slot,
                        "reason": reason,
                    },
                )
                audit_action = "ARTICLE_DUPLICATE_APPROVED"
            else:
                conflict = get_object_or_404(ArticleIngestConflict, pk=pk)
                article_id = serializer.validated_data.get("article_id")
                linked_article = get_object_or_404(Article, pk=article_id) if article_id else conflict.existing_article
                conflict = link_source_ingest_conflict(
                    conflict_id=pk,
                    linked_article=linked_article,
                    reviewed_by=actor,
                    review_reason=reason,
                )
                record_audit(
                    request,
                    action_type="ARTICLE_DUPLICATE_LINKED",
                    target_type="article",
                    target_id=linked_article.id,
                    after_data={
                        "conflict_id": conflict.id,
                        "linked_article_id": linked_article.id,
                        "reason": reason,
                    },
                )
                audit_action = "ARTICLE_DUPLICATE_LINKED"
        except (ArticleIngestConflict.DoesNotExist, ValueError, PermissionError) as error:
            return Response(
                {"success": False, "error": {"code": "CONFLICT_REVIEW_FAILED", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="SOURCE_INGEST_CONFLICT_REVIEWED",
            target_type="ArticleIngestConflict",
            target_id=conflict.id,
            after_data={"status": conflict.status, "reason": reason, "article_action": audit_action},
        )
        return ok(ArticleIngestConflictSerializer(conflict).data)
