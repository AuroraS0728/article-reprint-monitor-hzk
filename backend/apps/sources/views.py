from __future__ import annotations

from datetime import datetime
from typing import cast

from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.articles.models import Article, ArticleStatus
from apps.audit.services import record_audit
from apps.core.permissions import CanOperate, IsAdministrator
from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.reposts.models import ContentRelation, RepostRecord

from .authentication import SourceTokenAuthentication
from .models import (
    ArticleIngestConflict,
    ArticleIngestConflictStatus,
    SearchProviderConfiguration,
    SearchRun,
    SearchRunCandidate,
    SourceIngestToken,
    TargetedCrawlTask,
)
from .serializers import (
    ArticleIngestConflictReviewSerializer,
    ArticleIngestConflictSerializer,
    ManualGlobalSearchSerializer,
    SearchProviderConfigurationSerializer,
    SearchRunCandidateReviewSerializer,
    SearchRunCandidateSerializer,
    SourceArticleIngestSerializer,
    TargetedCrawlCandidatesSerializer,
    TargetedCrawlRunSerializer,
)
from .services import (
    approve_source_ingest_conflict,
    claim_targeted_crawl_task,
    complete_targeted_crawl_run,
    due_targeted_crawl_tasks,
    ingest_source_article,
    link_source_ingest_conflict,
    review_search_candidate,
    submit_targeted_crawl_candidates,
    targeted_crawl_dispatch_state,
)
from .tasks import search_article_reposts


class SearchProviderConfigurationListCreateView(APIView):
    """Administrator-only source configuration; credentials are never API data."""

    permission_classes = [IsAdministrator]
    serializer_class = SearchProviderConfigurationSerializer

    def get(self, request: Request) -> Response:
        configurations = SearchProviderConfiguration.objects.all()
        return ok(SearchProviderConfigurationSerializer(configurations, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = SearchProviderConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        configuration = serializer.save()
        record_audit(
            request,
            action_type="SEARCH_PROVIDER_CONFIGURATION_CREATE",
            target_type="SearchProviderConfiguration",
            target_id=configuration.id,
            after_data=SearchProviderConfigurationSerializer(configuration).data,
        )
        return ok(SearchProviderConfigurationSerializer(configuration).data, status.HTTP_201_CREATED)


class SearchProviderConfigurationDetailView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = SearchProviderConfigurationSerializer

    def patch(self, request: Request, pk: int) -> Response:
        configuration = get_object_or_404(SearchProviderConfiguration, pk=pk)
        before = SearchProviderConfigurationSerializer(configuration).data
        serializer = SearchProviderConfigurationSerializer(configuration, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        configuration = serializer.save()
        record_audit(
            request,
            action_type="SEARCH_PROVIDER_CONFIGURATION_UPDATE",
            target_type="SearchProviderConfiguration",
            target_id=configuration.id,
            before_data=before,
            after_data=SearchProviderConfigurationSerializer(configuration).data,
        )
        return ok(SearchProviderConfigurationSerializer(configuration).data)


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
                channel_code=cast(str, data.get("channel_code", "")),
                channel_name=cast(str, data.get("channel_name", "")),
                section_code=cast(str, data.get("section_code", "")),
                section_name=cast(str, data.get("section_name", "")),
            )
        except ValueError as error:
            return Response(
                {
                    "success": False,
                    "error": {"code": "INVALID_SOURCE_ARTICLE", "message": str(error)},
                },
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
            action_type=("SOURCE_ARTICLE_CREATE" if result.created else "SOURCE_ARTICLE_UPDATE"),
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
            "source",
            "existing_article",
            "created_article",
            "linked_article",
            "created_by",
            "reviewed_by",
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
                    "exact_candidate_count": run.exact_candidate_count,
                    "broad_candidate_count": run.broad_candidate_count,
                    "merged_candidate_count": run.merged_candidate_count,
                    "matched_count": run.matched_count,
                    "owned_count": run.owned_count,
                    "repost_count": run.repost_count,
                    "review_required_count": run.review_required_count,
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
        data = serializer.validated_data
        selection_mode = cast(str, data.get("selection_mode", "IDS"))
        if selection_mode == "FILTER":
            filters = cast(dict[str, object], data["filters"])
            selected = Article.objects.all()
            if value := filters.get("published_from"):
                selected = selected.filter(published_date__gte=str(value))
            if value := filters.get("published_to"):
                selected = selected.filter(published_date__lte=str(value))
            if value := filters.get("channel"):
                selected = selected.filter(channel_code=str(value))
            if value := filters.get("section"):
                selected = selected.filter(section_code=str(value))
            if value := filters.get("monitoring_status"):
                selected = selected.filter(monitoring_status=str(value))
            if value := filters.get("q"):
                selected = selected.filter(title__icontains=str(value))
            reposts = RepostRecord.objects.filter(
                article_id=OuterRef("pk"),
                is_valid=True,
                content_relation=ContentRelation.REPOST,
            )
            if value := filters.get("site_domain"):
                selected = selected.filter(Exists(reposts.filter(site_domain__iexact=str(value))))
            if (value := str(filters.get("has_repost", "")).lower()) in {"true", "false"}:
                selected = selected.filter(Exists(reposts) if value == "true" else ~Exists(reposts))
            article_ids = list(selected.order_by("id").values_list("id", flat=True)[:501])
            if len(article_ids) > 500:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "MANUAL_SEARCH_LIMIT",
                            "message": "一次最多检测 500 篇，请缩小筛选范围。",
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            article_ids = cast(list[int], data["article_ids"])
        articles = list(Article.objects.filter(id__in=article_ids).only("id", "status"))
        found_ids = {article.id for article in articles}
        missing_ids = sorted(set(article_ids) - found_ids)
        unavailable_ids = sorted(article.id for article in articles if article.status == ArticleStatus.ARCHIVED)
        if missing_ids or unavailable_ids:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "MANUAL_SEARCH_ARTICLE_UNAVAILABLE",
                        "message": "手动全网检测仅支持状态为监测中的文章。",
                        "details": {
                            "missing_article_ids": missing_ids,
                            "unavailable_article_ids": unavailable_ids,
                        },
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        for article in articles:
            search_article_reposts.delay(article.id, manual=True)
        record_audit(
            request,
            action_type=(
                "REPOST_SEARCH_FILTER_BATCH"
                if selection_mode == "FILTER"
                else ("REPOST_SEARCH_MANUAL_SINGLE" if len(article_ids) == 1 else "REPOST_SEARCH_MANUAL_BATCH")
            ),
            target_type="Article",
            target_id="manual-global-search",
            after_data={
                "article_ids": article_ids,
                "count": len(article_ids),
                "selection_mode": selection_mode,
            },
        )
        return ok(
            {"article_ids": article_ids, "queued_count": len(article_ids)},
            status.HTTP_202_ACCEPTED,
        )


class SearchRunCandidateListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SearchRunCandidateSerializer

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(SearchRun, pk=pk)
        candidates = SearchRunCandidate.objects.filter(search_run_id=pk)
        return ok(SearchRunCandidateSerializer(candidates, many=True).data)


class SearchRunCandidateReviewView(APIView):
    permission_classes = [CanOperate]
    serializer_class = SearchRunCandidateReviewSerializer

    def post(self, request: Request, pk: int) -> Response:
        serializer = SearchRunCandidateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate = get_object_or_404(SearchRunCandidate.objects.select_related("search_run__article"), pk=pk)
        before_data = {
            "disposition": candidate.disposition,
            "content_relation": candidate.content_relation,
            "owned_channel_id": candidate.owned_channel_id,
            "classification_reason": candidate.classification_reason,
        }
        try:
            reviewed, record = review_search_candidate(
                candidate_id=candidate.id,
                action=cast(str, serializer.validated_data["action"]),
                reason=cast(str, serializer.validated_data["reason"]),
                owned_channel_id=cast(int | None, serializer.validated_data.get("owned_channel_id")),
            )
        except (SearchRunCandidate.DoesNotExist, ValueError) as error:
            return Response(
                {"success": False, "error": {"code": "CANDIDATE_REVIEW_FAILED", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="SEARCH_CANDIDATE_REVIEWED",
            target_type="SearchRunCandidate",
            target_id=reviewed.id,
            before_data=before_data,
            after_data={
                "action": serializer.validated_data["action"],
                "reason": serializer.validated_data["reason"],
                "content_relation": reviewed.content_relation,
                "owned_channel_id": reviewed.owned_channel_id,
                "repost_record_id": record.id if record else None,
            },
        )
        return ok(SearchRunCandidateSerializer(reviewed).data)


def _targeted_crawl_task_payload(task: TargetedCrawlTask) -> dict[str, object]:
    article = task.article
    now = timezone.now()
    confirmed_repost_count = RepostRecord.objects.filter(
        article=article,
        content_relation=ContentRelation.REPOST,
        is_valid=True,
    ).count()
    return {
        "id": task.id,
        "article_id": article.id,
        "query": task.query,
        "title": article.title,
        "published_at": article.published_at,
        "original_url": article.original_url,
        "monitor_until": article.monitor_until,
        "status": task.status,
        "dispatch_state": targeted_crawl_dispatch_state(task, now=now),
        "first_scan_done": task.first_scan_done,
        "first_scan_completed_at": task.first_scan_completed_at,
        "confirmed_repost_count": confirmed_repost_count,
        "attempt_count": task.attempt_count,
        "next_available_at": task.next_available_at,
        "claim_expires_at": task.claim_expires_at,
    }


class TargetedCrawlTaskListView(APIView):
    """Lease only the authenticated source's due browser-search tasks."""

    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    @extend_schema(operation_id="targeted_crawl_task_list", responses=EmptySerializer)
    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", "1"))
        except ValueError:
            return Response(
                {"success": False, "error": {"code": "INVALID_LIMIT", "message": "limit 必须是整数。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= limit <= 20:
            return Response(
                {"success": False, "error": {"code": "INVALID_LIMIT", "message": "limit 必须在 1 到 20 之间。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        token = cast(SourceIngestToken, request.auth)
        tasks = due_targeted_crawl_tasks(source=token.source, limit=limit)
        return ok({"tasks": [_targeted_crawl_task_payload(task) for task in tasks]})


class TargetedCrawlTaskClaimView(APIView):
    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    @extend_schema(operation_id="targeted_crawl_task_claim", request=EmptySerializer, responses=EmptySerializer)
    def post(self, request: Request, pk: int) -> Response:
        token = cast(SourceIngestToken, request.auth)
        try:
            task, run, claim_token = claim_targeted_crawl_task(task_id=pk, token=token)
        except PermissionError as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_CLAIM_DENIED", "message": str(error)}},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_UNAVAILABLE", "message": str(error)}},
                status=status.HTTP_409_CONFLICT,
            )
        record_audit(
            request,
            action_type="TARGETED_CRAWL_TASK_CLAIMED",
            target_type="TargetedCrawlTask",
            target_id=task.id,
            after_data={"run_id": run.id, "article_id": task.article_id},
        )
        return ok(
            {
                "task": _targeted_crawl_task_payload(task),
                "run_id": run.id,
                "claim_token": claim_token,
            },
            status.HTTP_201_CREATED,
        )


class TargetedCrawlCandidatesView(APIView):
    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TargetedCrawlCandidatesSerializer

    def post(self, request: Request) -> Response:
        serializer = TargetedCrawlCandidatesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = cast(SourceIngestToken, request.auth)
        try:
            candidates = submit_targeted_crawl_candidates(
                task_id=cast(int, data["task_id"]),
                run_id=cast(int, data["run_id"]),
                claim_token=cast(str, data["claim_token"]),
                token=token,
                items=cast(list[dict[str, object]], data["candidates"]),
            )
        except PermissionError as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_LEASE_INVALID", "message": str(error)}},
                status=status.HTTP_403_FORBIDDEN,
            )
        except (ValueError, TypeError) as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_CANDIDATE_INVALID", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="TARGETED_CRAWL_CANDIDATES_SUBMITTED",
            target_type="SearchRun",
            target_id=cast(int, data["run_id"]),
            after_data={"task_id": data["task_id"], "candidate_count": len(candidates)},
        )
        return ok(SearchRunCandidateSerializer(candidates, many=True).data, status.HTTP_201_CREATED)


class TargetedCrawlRunCompleteView(APIView):
    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TargetedCrawlRunSerializer

    def post(self, request: Request) -> Response:
        serializer = TargetedCrawlRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = cast(SourceIngestToken, request.auth)
        try:
            task, run = complete_targeted_crawl_run(
                task_id=cast(int, data["task_id"]),
                run_id=cast(int, data["run_id"]),
                claim_token=cast(str, data["claim_token"]),
                token=token,
                run_status=cast(str, data["status"]),
                error_code=cast(str, data.get("error_code", "")),
                error_message=cast(str, data.get("error_message", "")),
            )
        except PermissionError as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_LEASE_INVALID", "message": str(error)}},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as error:
            return Response(
                {"success": False, "error": {"code": "TARGETED_CRAWL_RUN_INVALID", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="TARGETED_CRAWL_RUN_COMPLETED",
            target_type="SearchRun",
            target_id=run.id,
            after_data={"task_id": task.id, "status": run.status, "candidate_count": run.candidate_count},
        )
        return ok(
            {
                "task": _targeted_crawl_task_payload(task),
                "run": {
                    "id": run.id,
                    "status": run.status,
                    "candidate_count": run.candidate_count,
                    "repost_count": run.repost_count,
                    "owned_count": run.owned_count,
                    "review_required_count": run.review_required_count,
                    "new_repost_count": run.new_repost_count,
                    "completed_at": run.completed_at,
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                },
            }
        )


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
        except (
            ArticleIngestConflict.DoesNotExist,
            ValueError,
            PermissionError,
        ) as error:
            return Response(
                {
                    "success": False,
                    "error": {"code": "CONFLICT_REVIEW_FAILED", "message": str(error)},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="SOURCE_INGEST_CONFLICT_REVIEWED",
            target_type="ArticleIngestConflict",
            target_id=conflict.id,
            after_data={
                "status": conflict.status,
                "reason": reason,
                "article_action": audit_action,
            },
        )
        return ok(ArticleIngestConflictSerializer(conflict).data)
