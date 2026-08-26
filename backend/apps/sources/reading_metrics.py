"""Reading-metric integration boundary for owned-channel publications."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx
from django.conf import settings
from django.db.models import DateTimeField, OuterRef, Q, Subquery
from django.utils import timezone

from apps.reposts.models import ContentRelation, RepostRecord

from .models import ReadingMetricObservation, ReadingMetricStatus


@dataclass(frozen=True)
class ReadingMetric:
    publication_url: str
    reading_count: int | None
    observed_at: datetime | None
    status: str
    error_message: str = ""


class ReadingMetricProvider(Protocol):
    code: str

    def fetch(self, *, publication_url: str) -> ReadingMetric:
        """Fetch one approved metric without credentials leaking into logs."""


def _extract_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        return int(digits) if digits else None
    return None


def _extract_reading_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for key in (
            "reading_count",
            "read_count",
            "views",
            "view_count",
            "count",
            "total",
            "num",
            "value",
        ):
            count = _extract_int(payload.get(key))
            if count is not None:
                return count
        for key in ("data", "result", "stats"):
            nested = payload.get(key)
            count = _extract_reading_count(nested)
            if count is not None:
                return count
    elif isinstance(payload, list):
        for item in payload:
            count = _extract_reading_count(item)
            if count is not None:
                return count
    return None


def _extract_title_map(payload: Any) -> dict[str, int | None]:
    title_map: dict[str, int | None] = {}
    if isinstance(payload, dict):
        direct_titles = payload.get("titles")
        if isinstance(direct_titles, dict):
            for title, details in direct_titles.items():
                title_map[str(title)] = _extract_reading_count(details)
        for key in ("data", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                for title, count in _extract_title_map(nested).items():
                    title_map.setdefault(title, count)
    elif isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("article_title") or item.get("name")
            if not title:
                continue
            title_map[str(title)] = _extract_reading_count(item)
    return title_map


def _request_json(path: str, payload: dict[str, Any]) -> Any:
    base_url = settings.READING_METRIC_BASE_URL
    if not base_url:
        raise ValueError("READING_METRIC_BASE_URL 未配置")
    response = httpx.post(
        f"{base_url}{path}",
        json=payload,
        timeout=settings.READING_METRIC_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def latest_observed_reading_metrics(
    records: list[RepostRecord], *, as_of: datetime | None = None
) -> dict[int, ReadingMetric]:
    record_ids = [record.id for record in records]
    if not record_ids:
        return {}

    observations = ReadingMetricObservation.objects.filter(repost_record_id__in=record_ids)
    if as_of is not None:
        observations = observations.filter(observed_at__lte=as_of, created_at__lte=as_of)
    observation_rows = observations.order_by("repost_record_id", "-observed_at", "-id").values(
        "repost_record_id", "reading_count", "observed_at", "status"
    )
    metrics: dict[int, ReadingMetric] = {}
    for observation in observation_rows:
        record_id = int(observation["repost_record_id"])
        if record_id in metrics:
            continue
        metrics[record_id] = ReadingMetric(
            publication_url="",
            reading_count=observation["reading_count"],
            observed_at=observation["observed_at"],
            status=ReadingMetricStatus(observation["status"]).label,
        )
    return metrics


def query_reading_metric_provider(records: Sequence[RepostRecord]) -> tuple[dict[int, ReadingMetric], str]:
    """Query the configured provider once for a batch; never invent a reading count."""
    if not settings.READING_METRIC_BASE_URL:
        return {}, "接口未配置"

    title_to_records: dict[str, list[RepostRecord]] = {}
    for record in records:
        title_to_records.setdefault(record.article.title.strip(), []).append(record)

    if not title_to_records:
        return {}, "无待检测记录"

    metrics: dict[int, ReadingMetric] = {}
    observed_at = timezone.now()
    provider_status = "自动检测成功"
    title_errors: dict[str, str] = {}
    try:
        batch_payload = {"titles": list(title_to_records)}
        batch_response = _request_json("/polls/api/query_titles/", batch_payload)
        title_map = _extract_title_map(batch_response)
    except Exception:
        title_map = {}
        provider_status = "自动检测部分失败"

    unresolved_titles = [title for title in title_to_records if title not in title_map]
    for title in unresolved_titles:
        try:
            single_response = _request_json("/polls/api/query_title_stats/", {"title": title})
            title_map[title] = _extract_reading_count(single_response)
        except Exception:
            title_errors[title] = "阅读量服务请求失败"
            provider_status = "自动检测部分失败"

    for title, matched_records in title_to_records.items():
        count = title_map.get(title)
        if title in title_errors:
            metric_status = ReadingMetricStatus.ERROR.label
        elif count is None:
            metric_status = ReadingMetricStatus.NOT_FOUND.label
        else:
            metric_status = ReadingMetricStatus.SUCCESS.label
        for record in matched_records:
            metrics[record.id] = ReadingMetric(
                publication_url=record.canonical_url or record.normalized_url,
                reading_count=count,
                observed_at=observed_at,
                status=metric_status,
                error_message=title_errors.get(title, ""),
            )
    return metrics, provider_status


def fetch_reading_metrics(
    records: list[RepostRecord], *, as_of: datetime | None = None
) -> tuple[dict[int, ReadingMetric], str]:
    """Read the latest persisted observations without triggering network work from a page request."""
    persisted_metrics = latest_observed_reading_metrics(records, as_of=as_of)
    for record in records:
        metric = persisted_metrics.get(record.id)
        if metric is not None and not metric.publication_url:
            persisted_metrics[record.id] = ReadingMetric(
                publication_url=record.canonical_url or record.normalized_url,
                reading_count=metric.reading_count,
                observed_at=metric.observed_at,
                status=metric.status,
            )
    if settings.READING_METRIC_BASE_URL:
        return persisted_metrics, "自动检测已启用"
    return persisted_metrics, "系统记录" if persisted_metrics else "接口待接入"


def collect_due_reading_metrics(*, now: datetime | None = None, limit: int | None = None) -> dict[str, int | str]:
    """Collect due owned-channel metrics and persist every real provider outcome."""
    if not settings.READING_METRIC_BASE_URL:
        return {"status": "NOT_CONFIGURED", "selected": 0, "created": 0}

    observed_before = (now or timezone.now()) - timedelta(minutes=settings.READING_METRIC_COLLECTION_INTERVAL_MINUTES)
    latest_observed_at = (
        ReadingMetricObservation.objects.filter(repost_record_id=OuterRef("pk"))
        .order_by("-observed_at", "-id")
        .values("observed_at")[:1]
    )
    records = list(
        RepostRecord.objects.filter(is_valid=True, content_relation=ContentRelation.OWNED)
        .annotate(latest_reading_observed_at=Subquery(latest_observed_at, output_field=DateTimeField()))
        .filter(Q(latest_reading_observed_at__isnull=True) | Q(latest_reading_observed_at__lte=observed_before))
        .select_related("article", "article__source", "owned_channel")
        .order_by("latest_reading_observed_at", "id")[: (limit or settings.READING_METRIC_COLLECTION_BATCH_SIZE)]
    )
    metrics, provider_status = query_reading_metric_provider(records)
    status_by_label = {label: value for value, label in ReadingMetricStatus.choices}
    observations = []
    for record in records:
        metric = metrics.get(record.id)
        if metric is None:
            continue
        observations.append(
            ReadingMetricObservation(
                repost_record=record,
                source_id=record.article.source_id,
                reading_count=metric.reading_count,
                status=status_by_label.get(metric.status, ReadingMetricStatus.ERROR),
                observed_at=metric.observed_at or timezone.now(),
                error_message=metric.error_message,
            )
        )
    ReadingMetricObservation.objects.bulk_create(observations)
    return {
        "status": provider_status,
        "selected": len(records),
        "created": len(observations),
        "success": sum(1 for item in observations if item.status == ReadingMetricStatus.SUCCESS),
        "not_found": sum(1 for item in observations if item.status == ReadingMetricStatus.NOT_FOUND),
        "failed": sum(1 for item in observations if item.status == ReadingMetricStatus.ERROR),
    }
