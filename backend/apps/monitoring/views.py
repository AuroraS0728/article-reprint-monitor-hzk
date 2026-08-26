from __future__ import annotations

from datetime import datetime, time
from uuid import uuid4

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article, ArticleStatus
from apps.audit.services import record_audit
from apps.core.permissions import CanOperate
from apps.core.views import ok
from apps.reposts.models import RepostRecord

from .batch_services import batch_statistics, create_batch
from .models import BatchStatus, DetectionBatch, DetectionResult, StatusSnapshot
from .serializers import (
    DetectionBatchCreateSerializer,
    DetectionBatchSerializer,
    DetectionResultSerializer,
    StatusSnapshotSerializer,
)
from .snapshot_services import matrix_data_as_of
from .tasks import run_detection_batch


class DetectionBatchListCreateView(APIView):
    serializer_class = DetectionBatchCreateSerializer

    def get_permissions(self):
        return (
            [CanOperate()]
            if self.request.method == "POST"
            else [permissions.IsAuthenticated()]
        )

    @extend_schema(operation_id="detection_batch_list")
    def get(self, request: Request) -> Response:
        return ok(
            DetectionBatchSerializer(DetectionBatch.objects.all()[:100], many=True).data
        )

    def post(self, request: Request) -> Response:
        serializer = DetectionBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            batch = create_batch(
                trigger="AUTOMATIC" if data["automatic"] else "IMMEDIATE",
                article_ids=data["article_ids"],
                platform_ids=data["platform_ids"],
                article_date_from=data.get("article_date_from"),
                article_date_to=data.get("article_date_to"),
                use_all_enabled_platforms=data["use_all_enabled_platforms"],
                created_by=request.user,
                idempotency_key=uuid4().hex,
            )
        except ValueError as error:
            return Response(
                {
                    "success": False,
                    "error": {"code": "VALIDATION_ERROR", "message": str(error)},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="DETECTION_BATCH_CREATE",
            target_type="DetectionBatch",
            target_id=batch.id,
            after_data={
                "trigger": batch.trigger,
                "article_ids": batch.article_ids,
                "platform_ids": batch.platform_ids,
            },
        )
        run_detection_batch.delay(batch.id)
        return ok(DetectionBatchSerializer(batch).data, status.HTTP_201_CREATED)


class DetectionBatchDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectionBatchSerializer

    @extend_schema(operation_id="detection_batch_retrieve")
    def get(self, request: Request, pk: int) -> Response:
        return ok(
            DetectionBatchSerializer(get_object_or_404(DetectionBatch, pk=pk)).data
        )


class DetectionSelectionDefaultsView(APIView):
    permission_classes = [CanOperate]
    serializer_class = DetectionBatchSerializer

    def get(self, request: Request) -> Response:
        latest_batch = (
            DetectionBatch.objects.filter(status=BatchStatus.COMPLETED)
            .order_by("-completed_at", "-id")
            .first()
        )
        articles = Article.objects.filter(status=ArticleStatus.ACTIVE)
        if latest_batch and latest_batch.created_at:
            articles = articles.filter(created_at__gt=latest_batch.created_at)
        return ok(
            {"article_ids": list(articles.order_by("id").values_list("id", flat=True))}
        )


class DetectionMatrixView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectionResultSerializer

    def get(self, request: Request, pk: int) -> Response:
        batch = get_object_or_404(DetectionBatch, pk=pk)
        results = DetectionResult.objects.filter(batch=batch).select_related(
            "article", "platform"
        )
        return ok(
            {
                "batch": DetectionBatchSerializer(batch).data,
                "results": DetectionResultSerializer(results, many=True).data,
            }
        )


class DetectionStatisticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectionBatchSerializer

    def get(self, request: Request, pk: int) -> Response:
        return ok(batch_statistics(get_object_or_404(DetectionBatch, pk=pk)))


class StatusMatrixView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectionResultSerializer

    def get(self, request: Request) -> Response:
        as_of = request.query_params.get("as_of")
        if not as_of:
            return ok({"as_of": None, "matrix": matrix_data_as_of()})
        try:
            requested_date = datetime.strptime(as_of, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_DATE",
                        "message": "as_of 必须为 YYYY-MM-DD。",
                    },
                },
                status=400,
            )
        cutoff_at = timezone.make_aware(datetime.combine(requested_date, time.max))
        return ok(
            {
                "as_of": cutoff_at.isoformat(),
                "matrix": matrix_data_as_of(cutoff_at=cutoff_at),
            }
        )


class StatusSnapshotListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StatusSnapshotSerializer

    def get(self, request: Request) -> Response:
        snapshots = StatusSnapshot.objects.all()
        snapshot_type = request.query_params.get("snapshot_type")
        if snapshot_type:
            snapshots = snapshots.filter(snapshot_type=snapshot_type)
        return ok(
            StatusSnapshotSerializer(
                snapshots.order_by("-cutoff_at")[:100], many=True
            ).data
        )


class DetectionResultRepostsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectionResultSerializer

    def get(self, request: Request, pk: int) -> Response:
        result = get_object_or_404(
            DetectionResult.objects.select_related("batch"), pk=pk
        )
        rows = RepostRecord.objects.filter(
            article=result.article, platform=result.platform, is_valid=True
        )
        if result.batch.completed_at:
            rows = rows.filter(first_discovered_at__lte=result.batch.completed_at)
        return ok(
            [
                {
                    "id": row.id,
                    "original_url": row.original_url,
                    "normalized_url": row.normalized_url,
                    "final_url": row.final_url,
                    "repost_title": row.repost_title,
                    "repost_published_at": row.repost_published_at,
                    "repost_published_display": (
                        row.repost_published_at.isoformat()
                        if row.repost_published_at
                        else "无"
                    ),
                    "first_discovered_at": row.first_discovered_at,
                    "last_checked_at": row.last_checked_at,
                    "data_source": row.data_source,
                }
                for row in rows
            ]
        )
