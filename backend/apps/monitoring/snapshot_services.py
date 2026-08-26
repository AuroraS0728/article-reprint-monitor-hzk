from __future__ import annotations

from datetime import datetime

from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce

from apps.reposts.models import RepostRecord

from .batch_services import batch_statistics
from .models import (
    DetectionBatch,
    DetectionResult,
    PlatformDetectionStatus,
    StatusSnapshot,
)


def _apply_historical_reposts(
    matrix: dict[str, dict[str, object]], *, cutoff_at: datetime | None = None
) -> None:
    records = RepostRecord.objects.filter(
        is_valid=True, platform_id__isnull=False
    ).annotate(
        historical_found_at=Coalesce(
            "first_found_at", "first_discovered_at", "created_at"
        )
    )
    if cutoff_at is not None:
        records = records.filter(historical_found_at__lte=cutoff_at)

    pairs: dict[tuple[int, int], str] = {}
    for article_id, platform_id, data_source in records.values_list(
        "article_id", "platform_id", "data_source"
    ):
        if platform_id is None:
            continue
        pair_key = (article_id, platform_id)
        if pair_key not in pairs or data_source == "MANUAL_SUPPLEMENT":
            pairs[pair_key] = data_source

    for (article_id, platform_id), data_source in pairs.items():
        cell_key = f"{article_id}:{platform_id}"
        item = matrix.get(
            cell_key,
            {
                "result_id": None,
                "article_id": article_id,
                "platform_id": platform_id,
                "completed_at": None,
            },
        )
        item["status"] = PlatformDetectionStatus.FOUND
        item["reason_code"] = (
            "MANUAL_SUPPLEMENT"
            if data_source == "MANUAL_SUPPLEMENT"
            else "HISTORICAL_REPOST"
        )
        matrix[cell_key] = item


def matrix_data_as_of(
    *, cutoff_at: datetime | None = None
) -> dict[str, dict[str, object]]:
    latest_rows = DetectionResult.objects.filter(
        article_id=OuterRef("article_id"), platform_id=OuterRef("platform_id")
    )
    if cutoff_at is not None:
        latest_rows = latest_rows.filter(completed_at__lte=cutoff_at)
    latest_ids = latest_rows.order_by("-completed_at", "-id").values("id")[:1]
    rows = DetectionResult.objects.filter(id=Subquery(latest_ids)).select_related(
        "article", "platform"
    )
    matrix = {
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
    _apply_historical_reposts(matrix, cutoff_at=cutoff_at)
    return matrix


def create_status_snapshot(
    *,
    snapshot_type: str,
    cutoff_at: datetime,
    source_batch: DetectionBatch | None = None,
) -> StatusSnapshot:
    matrix_data = matrix_data_as_of(cutoff_at=cutoff_at)
    # A weekly report is based on the dedicated final-detection batch.  That
    # batch may complete a few minutes after the nominal 07:00 cutoff, so a
    # plain "completed_at <= cutoff" query would incorrectly discard its
    # results.  Overlaying the selected source batch preserves the required
    # final state without changing historical daily snapshots.
    if source_batch is not None:
        for row in DetectionResult.objects.filter(batch=source_batch).select_related(
            "article", "platform"
        ):
            matrix_data[f"{row.article_id}:{row.platform_id}"] = {
                "result_id": row.id,
                "article_id": row.article_id,
                "platform_id": row.platform_id,
                "status": row.status,
                "reason_code": row.reason_code,
                "completed_at": (
                    row.completed_at.isoformat() if row.completed_at else None
                ),
            }
        _apply_historical_reposts(matrix_data, cutoff_at=cutoff_at)
    statistics_data = (
        batch_statistics(source_batch, cutoff_at=cutoff_at)
        if source_batch
        else {
            "article_total": len({item["article_id"] for item in matrix_data.values()}),
            "platform_total": len(
                {item["platform_id"] for item in matrix_data.values()}
            ),
        }
    )
    snapshot, _ = StatusSnapshot.objects.update_or_create(
        snapshot_type=snapshot_type,
        cutoff_at=cutoff_at,
        defaults={
            "source_batch": source_batch,
            "matrix_data": matrix_data,
            "statistics_data": statistics_data,
        },
    )
    return snapshot
