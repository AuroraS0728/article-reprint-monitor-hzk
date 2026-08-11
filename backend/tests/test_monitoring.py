from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.articles.models import Article
from apps.monitoring.batch_services import batch_statistics, create_batch
from apps.monitoring.models import DetectionResult, PlatformDetectionStatus, SnapshotType
from apps.monitoring.services import SearchOutcome, evaluate_detection
from apps.monitoring.snapshot_services import create_status_snapshot, matrix_data_as_of
from apps.platforms.models import Platform, PlatformStatus
from apps.reposts.models import RepostRecord
from tests.fixtures.test_adapter import FixtureAdapter, candidate

from .test_article_platform import client_for


class UnexpectedAdapter:
    def search_exact_title(self, *, article: Article, platform: Platform) -> SearchOutcome:
        raise AssertionError("历史转载已经确认后，不应再次调用平台适配器。")


def enabled_platform(*, code: str, suffixes: list[str] | None = None) -> Platform:
    return Platform.objects.create(
        code=code,
        name=code,
        status=PlatformStatus.ENABLED,
        confirmed_title_suffixes=suffixes or [],
    )


def article(*, title: str = "转载监测 标题", published_date: date = date(2026, 8, 6), created_by: object) -> Article:
    return Article.objects.create(
        title=title,
        normalized_title=title,
        published_date=published_date,
        created_by=created_by,
    )


@pytest.mark.django_db
def test_result_status_never_converts_unconfirmed_or_failure_to_not_found(operator: object) -> None:
    source = article(created_by=operator)
    platform = enabled_platform(code="UNKNOWN_PLATFORM")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="unknown-status",
    )
    result = batch.results.get()

    evaluate_detection(result=result, adapter=FixtureAdapter(completed=False))

    result.refresh_from_db()
    assert result.status == PlatformDetectionStatus.UNKNOWN
    assert result.reason_code == "FIXTURE_UNCONFIRMED"


@pytest.mark.django_db
def test_exact_normalized_match_preserves_all_distinct_urls_and_missing_publish_time(operator: object) -> None:
    source = article(created_by=operator, title="“全角”  标题")
    platform = enabled_platform(code="MATCH_PLATFORM", suffixes=["新闻网"])
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="exact-match",
    )
    result = batch.results.get()
    adapter = FixtureAdapter(
        completed=True,
        candidates=(
            candidate(url="https://example.com/a?utm_source=x", title='"全角" 标题 - 新闻网'),
            candidate(url="https://example.com/b", title='"全角" 标题 - 新闻网'),
            candidate(url="https://example.com/other", title="不同标题"),
        ),
    )

    evaluate_detection(result=result, adapter=adapter)

    result.refresh_from_db()
    assert result.status == PlatformDetectionStatus.FOUND
    assert RepostRecord.objects.filter(article=source, platform=platform).count() == 2
    assert RepostRecord.objects.filter(repost_published_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_historical_repost_prevents_repeat_request_and_keeps_legacy_matrix_found(operator: object) -> None:
    source = article(created_by=operator)
    platform = enabled_platform(code="STICKY_PLATFORM")
    first_batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="sticky-found-first",
    )
    first_result = first_batch.results.get()
    evaluate_detection(
        result=first_result,
        adapter=FixtureAdapter(
            completed=True,
            candidates=(candidate(url="https://example.com/sticky", title=source.title),),
        ),
    )

    second_batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="sticky-found-second",
    )
    second_result = second_batch.results.get()
    evaluate_detection(result=second_result, adapter=UnexpectedAdapter())
    second_result.refresh_from_db()

    assert second_result.status == PlatformDetectionStatus.FOUND
    assert second_result.reason_code == "HISTORICAL_REPOST"
    assert second_result.attempt_count == 0
    key = f"{source.id}:{platform.id}"
    assert matrix_data_as_of()[key]["status"] == PlatformDetectionStatus.FOUND
    assert batch_statistics(second_batch)["article_reposted_count"] == 1

    DetectionResult.objects.filter(id=second_result.id).update(
        status=PlatformDetectionStatus.NOT_FOUND,
        reason_code="",
    )
    assert matrix_data_as_of()[key]["status"] == PlatformDetectionStatus.FOUND
    snapshot = create_status_snapshot(
        snapshot_type=SnapshotType.WEEKLY,
        cutoff_at=second_result.completed_at,
        source_batch=second_batch,
    )
    assert snapshot.matrix_data[key]["status"] == PlatformDetectionStatus.FOUND


@pytest.mark.django_db
def test_completed_empty_result_is_not_found_and_statistics_keep_unknown_in_denominator(operator: object) -> None:
    source = article(created_by=operator)
    found_platform = enabled_platform(code="FOUND_PLATFORM")
    unknown_platform = enabled_platform(code="SECOND_PLATFORM")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[found_platform.id, unknown_platform.id],
        created_by=operator,
        idempotency_key="statistics-denominator",
    )
    found_result = DetectionResult.objects.get(batch=batch, platform=found_platform)
    unknown_result = DetectionResult.objects.get(batch=batch, platform=unknown_platform)
    evaluate_detection(
        result=found_result,
        adapter=FixtureAdapter(
            completed=True, candidates=(candidate(url="https://example.com/a", title=source.title),)
        ),
    )
    evaluate_detection(result=unknown_result, adapter=FixtureAdapter(completed=False))

    stats = batch_statistics(batch)
    assert stats["article_repost_rate"] == 1
    assert stats["detection_completion_rate"] == 0.5
    assert stats["per_article"] == [
        {
            "article_id": source.id,
            "reposted_platform_count": 1,
            "platform_repost_rate": 0.5,
            "completed_platform_count": 1,
            "detection_completion_rate": 0.5,
        }
    ]


@pytest.mark.django_db
def test_batch_date_range_all_enabled_and_permission(operator: object, viewer: object) -> None:
    selected = article(created_by=operator, published_date=date(2026, 8, 6))
    article(created_by=operator, published_date=date(2026, 7, 1))
    platform = enabled_platform(code="DATE_RANGE_PLATFORM")
    client = client_for(operator)
    payload = {
        "article_date_from": "2026-08-01",
        "article_date_to": "2026-08-31",
        "use_all_enabled_platforms": True,
    }

    response = client.post("/api/v1/detection-batches", payload, format="json")
    assert response.status_code == 201
    assert response.json()["data"]["article_ids"] == [selected.id]
    assert response.json()["data"]["platform_ids"] == [platform.id]
    assert client_for(viewer).post("/api/v1/detection-batches", payload, format="json").status_code == 403
    assert APIClient().get("/api/v1/detection-batches").status_code == 403


@pytest.mark.django_db
def test_current_and_historical_matrix_only_use_results_available_at_cutoff(operator: object) -> None:
    source = article(created_by=operator)
    platform = enabled_platform(code="HISTORY_PLATFORM")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[source.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="history-matrix",
    )
    result = batch.results.get()
    evaluate_detection(result=result, adapter=FixtureAdapter(completed=True, candidates=()))
    result.refresh_from_db()
    assert result.completed_at is not None

    snapshot = create_status_snapshot(
        snapshot_type=SnapshotType.DAILY,
        cutoff_at=result.completed_at,
        source_batch=batch,
    )

    assert snapshot.matrix_data[f"{source.id}:{platform.id}"]["status"] == PlatformDetectionStatus.NOT_FOUND
    current_matrix = matrix_data_as_of(cutoff_at=result.completed_at)
    assert current_matrix[f"{source.id}:{platform.id}"]["status"] == PlatformDetectionStatus.NOT_FOUND
    assert current_matrix[f"{source.id}:{platform.id}"]["result_id"] == result.id

    response = client_for(operator).get("/api/v1/status-matrix")
    assert response.status_code == 200
    assert response.json()["data"]["matrix"][f"{source.id}:{platform.id}"]["result_id"] == result.id
