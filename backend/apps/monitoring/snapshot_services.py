from __future__ import annotations

from datetime import datetime

from django.db.models import OuterRef, Subquery

from .batch_services import batch_statistics
from .models import DetectionBatch, DetectionResult, StatusSnapshot


def matrix_data_as_of(*, cutoff_at: datetime | None = None) -> dict[str, dict[str, object]]:
    latest_rows = DetectionResult.objects.filter(article_id=OuterRef("article_id"), platform_id=OuterRef("platform_id"))
    if cutoff_at is not None:
        latest_rows = latest_rows.filter(completed_at__lte=cutoff_at)
    latest_ids = latest_rows.order_by("-completed_at", "-id").values("id")[:1]
    rows = DetectionResult.objects.filter(id=Subquery(latest_ids)).select_related("article", "platform")
    return {
        f"{row.article_id}:{row.platform_id}": {
            "result_id": row.id,
            "article_id": row.article_id,
            "platform_id": row.platform_id,
            "status": row.status,
            "reason_code": row.reason_code,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
        for row in rows
    }


def create_status_snapshot(
    *, snapshot_type: str, cutoff_at: datetime, source_batch: DetectionBatch | None = None
) -> StatusSnapshot:
    matrix_data = matrix_data_as_of(cutoff_at=cutoff_at)
    statistics_data = (
        batch_statistics(source_batch)
        if source_batch
        else {
            "article_total": len({item["article_id"] for item in matrix_data.values()}),
            "platform_total": len({item["platform_id"] for item in matrix_data.values()}),
        }
    )
    snapshot, _ = StatusSnapshot.objects.update_or_create(
        snapshot_type=snapshot_type,
        cutoff_at=cutoff_at,
        defaults={"source_batch": source_batch, "matrix_data": matrix_data, "statistics_data": statistics_data},
    )
    return snapshot
