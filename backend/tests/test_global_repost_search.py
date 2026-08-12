from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.articles.models import Article, ArticleIngestMethod, ArticleMonitoringStatus
from apps.reposts.export_services import (
    EXCEL_DATETIME_FORMAT,
    GlobalExportFilters,
    build_global_repost_workbook,
    filtered_articles,
    sanitize_excel_sheet_name,
)
from apps.reposts.models import RepostRecord
from apps.sources.models import SearchCandidateDisposition, SearchRunCandidate, SearchRunStatus, Source
from apps.sources.services import (
    _next_search_time,
    canonicalize_http_url,
    compare_titles,
    ingest_source_article,
    mark_repost_availability,
    purge_expired_source_articles,
    search_article,
)
from apps.sources.tasks import search_article_reposts
from apps.sources.token_services import create_source_token
from search_providers.exceptions import SearchProviderRateLimited
from search_providers.types import SearchCandidate


@dataclass
class StaticProvider:
    candidates: list[SearchCandidate]
    code: str = "test-provider"

    def search(self, query: str, **kwargs: object) -> list[SearchCandidate]:
        return list(self.candidates)


class ErrorProvider:
    code = "test-provider"

    def search(self, query: str, **kwargs: object) -> list[SearchCandidate]:
        raise SearchProviderRateLimited("rate limited")


@pytest.fixture
def source(db: object) -> Source:
    source, _ = Source.objects.update_or_create(
        code="WEEKLYONSTOCK",
        defaults={
            "name": "证券市场周刊",
            "base_url": "https://www.weeklyonstock.com/",
            "is_active": True,
        },
    )
    return source


def create_source_article(*, source: Source, operator: User, days_old: int = 0) -> Article:
    published_at = timezone.now() - timedelta(days=days_old)
    return ingest_source_article(
        source=source,
        title="这一主线再掀涨停潮！低位方向正在成为新主角？",
        author="木木",
        published_at=published_at,
        original_url="https://www.weeklyonstock.com/article/123?utm_source=feed",
        created_by=operator,
    ).article


@pytest.mark.django_db
def test_source_token_is_hashed_and_ingest_api_is_idempotent(source: Source, operator: User) -> None:
    created_token = create_source_token(source=source, name="browser", created_by=operator)
    assert created_token.record.token_hash != created_token.plaintext
    assert created_token.plaintext not in created_token.record.token_prefix
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {created_token.plaintext}")
    payload = {
        "title": "原创标题",
        "author": "作者",
        "published_at": timezone.now().isoformat(),
        "original_url": "https://www.weeklyonstock.com/article/ingest?utm_source=browser",
    }
    with patch("apps.sources.tasks.search_article_reposts.delay"):
        first = client.post("/api/v1/source-ingest/articles", payload, format="json")
        second = client.post("/api/v1/source-ingest/articles", payload, format="json")
        payload["title"] = "修改后的原创标题"
        third = client.post("/api/v1/source-ingest/articles", payload, format="json")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["updated"] is False
    assert third.status_code == 200
    assert third.json()["data"]["updated"] is True
    assert Article.objects.filter(source=source).count() == 1
    article = Article.objects.get(source=source)
    assert article.title == "修改后的原创标题"
    assert article.ingest_method == ArticleIngestMethod.SOURCE_API


@pytest.mark.django_db
def test_source_ingest_rejects_invalid_expired_inactive_tokens_and_source(source: Source, operator: User) -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
    assert client.post("/api/v1/source-ingest/articles", {}, format="json").status_code == 401

    payload = {
        "title": "原创标题",
        "author": "作者",
        "published_at": timezone.now().isoformat(),
        "original_url": "https://www.weeklyonstock.com/a",
    }
    for token_changes, source_active in [
        ({"expires_at": timezone.now() - timedelta(seconds=1)}, True),
        ({"is_active": False}, True),
        ({}, False),
    ]:
        source.is_active = source_active
        source.save(update_fields=["is_active"])
        created = create_source_token(source=source, name="test", created_by=operator)
        for field, value in token_changes.items():
            setattr(created.record, field, value)
        created.record.save()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {created.plaintext}")
        assert client.post("/api/v1/source-ingest/articles", payload, format="json").status_code == 401


@pytest.mark.django_db
def test_expired_first_ingest_is_completed_without_restarting_monitoring(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator, days_old=8)
    assert article.monitoring_status == ArticleMonitoringStatus.COMPLETED
    assert article.next_search_at is None
    original_until = article.monitor_until
    result = ingest_source_article(
        source=source,
        title=f"{article.title} 修改",
        author="木木",
        published_at=article.published_at,
        original_url=article.original_url,
        created_by=operator,
    )
    assert result.article.monitor_until == original_until
    assert result.article.monitoring_status == ArticleMonitoringStatus.COMPLETED


@pytest.mark.django_db
def test_manual_global_search_allows_completed_article_without_restarting_lifecycle(
    source: Source, operator: User
) -> None:
    article = create_source_article(source=source, operator=operator, days_old=8)
    original_next_search_at = article.next_search_at
    with patch("apps.sources.tasks.search_article", return_value=SimpleNamespace(id=77, status="SUCCESS")) as search:
        assert search_article_reposts.run(article.id, manual=True) == 77
    article.refresh_from_db()
    assert search.called
    assert article.monitoring_status == ArticleMonitoringStatus.COMPLETED
    assert article.next_search_at == original_next_search_at


@pytest.mark.django_db
def test_manual_global_search_api_queues_unarchived_articles_and_rejects_archived(
    source: Source, operator: User
) -> None:
    article = create_source_article(source=source, operator=operator)
    client = APIClient()
    client.force_authenticate(operator)
    with patch("apps.sources.views.search_article_reposts.delay") as delay:
        response = client.post("/api/v1/global-search-runs", {"article_ids": [article.id]}, format="json")
    assert response.status_code == 202
    assert response.json()["data"]["queued_count"] == 1
    delay.assert_called_once_with(article.id, manual=True)
    article.status = "ARCHIVED"
    article.save(update_fields=["status"])
    response = client.post("/api/v1/global-search-runs", {"article_ids": [article.id]}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_search_run_candidates_are_available_to_authenticated_readers(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    run = search_article(
        article,
        provider=StaticProvider(
            [SearchCandidate(title="候选页", url="https://finance.example.com/a", site_name="示例财经")]
        ),
    )
    client = APIClient()
    client.force_authenticate(operator)
    response = client.get(f"/api/v1/global-search-runs/{run.id}/candidates")
    assert response.status_code == 200
    candidate = response.json()["data"][0]
    assert candidate["title"] == "候选页"
    assert candidate["site_name"] == "示例财经"
    assert candidate["canonical_url"] == "https://finance.example.com/a"


def test_url_canonicalization_and_similarity_threshold() -> None:
    assert canonicalize_http_url("HTTPS://Example.COM:443/a?utm_source=x&a=1#fragment") == "https://example.com/a?a=1"
    with pytest.raises(ValueError):
        canonicalize_http_url("http://127.0.0.1/private")
    exact = compare_titles(
        "标题：测试！",
        SearchCandidate(title="标题测试 - 某网站", url="https://example.com/1", site_name="某网站"),
    )
    assert exact.matched is True
    assert exact.similarity_score == 100
    with override_settings(SEARCH_SHORT_TITLE_LENGTH=1, SEARCH_SIMILARITY_THRESHOLD=90):
        with patch("apps.sources.services.fuzz.ratio", return_value=89.99):
            assert (
                compare_titles("足够长的测试标题", SearchCandidate(title="另一标题", url="https://a.com")).matched
                is False
            )
        with patch("apps.sources.services.fuzz.ratio", return_value=90.0):
            assert (
                compare_titles("足够长的测试标题", SearchCandidate(title="另一标题", url="https://a.com")).matched
                is True
            )


@pytest.mark.django_db
def test_global_search_deduplicates_urls_excludes_source_and_preserves_history(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    title = article.title
    candidates = [
        SearchCandidate(title=title, url="https://news.example.com/1?a=1&utm_source=x", site_name="示例财经"),
        SearchCandidate(title=title, url="https://news.example.com/1?utm_source=y&a=1", site_name="示例财经"),
        SearchCandidate(title=title, url="https://news.example.com/2", site_name="示例财经"),
        SearchCandidate(title=title, url="https://static.weeklyonstock.com/copy", site_name="原站"),
    ]
    first_run = search_article(article, provider=StaticProvider(candidates))
    assert first_run.status == SearchRunStatus.SUCCESS
    assert SearchRunCandidate.objects.filter(search_run=first_run).count() == 3
    assert (
        SearchRunCandidate.objects.filter(
            search_run=first_run, disposition=SearchCandidateDisposition.EXCLUDED_SOURCE
        ).count()
        == 1
    )
    assert RepostRecord.objects.filter(article=article).count() == 2
    first_record = RepostRecord.objects.filter(article=article).order_by("canonical_url").first()
    assert first_record is not None
    first_found = first_record.first_found_at

    search_article(article, provider=StaticProvider([]))
    assert RepostRecord.objects.filter(article=article).count() == 2
    mark_repost_availability(record=first_record, status="REMOVED")
    first_record.refresh_from_db()
    assert first_record.first_found_at == first_found
    assert first_record.availability_status == "REMOVED"
    assert RepostRecord.objects.filter(article=article, is_valid=True).count() == 2


@pytest.mark.django_db
def test_provider_error_keeps_article_active_and_existing_reposts(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    search_article(
        article,
        provider=StaticProvider([SearchCandidate(title=article.title, url="https://example.com/repost")]),
    )
    run = search_article(article, provider=ErrorProvider())
    article.refresh_from_db()
    assert run.status == SearchRunStatus.ERROR
    assert run.error_code == "SEARCH_PROVIDER_RATE_LIMITED"
    assert article.monitoring_status == ArticleMonitoringStatus.ACTIVE
    assert RepostRecord.objects.filter(article=article).count() == 1


@pytest.mark.django_db
@override_settings(SEARCH_PROVIDER="", BRAVE_SEARCH_API_KEY="")
def test_unconfigured_provider_records_explicit_error_without_fake_results(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    run = search_article(article)
    assert run.status == SearchRunStatus.ERROR
    assert run.error_code == "SEARCH_PROVIDER_NOT_CONFIGURED"
    assert RepostRecord.objects.filter(article=article).count() == 0


@pytest.mark.django_db
def test_repeated_discovery_updates_last_seen_without_changing_first_found(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    provider = StaticProvider([SearchCandidate(title=article.title, url="https://example.com/sticky")])
    search_article(article, provider=provider)
    record = RepostRecord.objects.get(article=article)
    first_found = record.first_found_at
    search_article(article, provider=provider)
    record.refresh_from_db()
    assert RepostRecord.objects.filter(article=article).count() == 1
    assert record.first_found_at == first_found
    assert record.last_seen_at is not None and first_found is not None and record.last_seen_at >= first_found


@pytest.mark.django_db
def test_retention_only_purges_after_article_retention(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    search_article(
        article,
        provider=StaticProvider([SearchCandidate(title=article.title, url="https://example.com/repost")]),
    )
    article.retention_until = timezone.now() + timedelta(days=1)
    article.save(update_fields=["retention_until"])
    assert purge_expired_source_articles()["articles_deleted"] == 0
    article.retention_until = timezone.now() - timedelta(seconds=1)
    article.save(update_fields=["retention_until"])
    assert purge_expired_source_articles()["articles_deleted"] == 1
    assert not Article.objects.filter(id=article.id).exists()


@pytest.mark.django_db
def test_dynamic_export_keeps_removed_links_and_creates_safe_site_sheets(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    now = timezone.now()
    for index, url in enumerate(("https://news.example.com/a", "https://news.example.com/b"), start=1):
        RepostRecord.objects.create(
            article=article,
            platform=None,
            site_name="危险:/网站名称很长很长很长很长很长很长很长很长",
            site_domain="news.example.com",
            raw_url=url,
            canonical_url=url,
            canonical_url_hash=str(index) * 64,
            original_url=url,
            normalized_url=url,
            normalized_url_hash=str(index) * 64,
            repost_title=f"{article.title} {index}",
            result_title=f"{article.title} {index}",
            similarity_score=95,
            first_discovered_at=now,
            first_found_at=now,
            last_checked_at=now,
            last_seen_at=now,
            availability_status="REMOVED" if index == 1 else "AVAILABLE",
            data_source="TEST_ONLY",
        )
    content, _ = build_global_repost_workbook(GlobalExportFilters(article_id=article.id))
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames[0] == "数据"
    assert workbook.sheetnames[-2:] == ["总统计", "统计汇总"]
    assert len(workbook.sheetnames) == 4
    assert len(workbook.sheetnames[1]) <= 31
    assert not INVALID_SHEET_CHARACTERS_FOR_TEST.search(workbook.sheetnames[1])
    assert "共2条" in workbook["数据"]["I2"].value
    assert workbook["数据"]["I2"].hyperlink.target == "https://news.example.com/a"
    assert workbook["数据"]["E2"].value == "监测中"
    assert workbook["数据"]["A2"].number_format == EXCEL_DATETIME_FORMAT
    assert workbook["数据"]["F2"].number_format == EXCEL_DATETIME_FORMAT
    site_sheet = workbook[workbook.sheetnames[1]]
    assert site_sheet.max_row == 3
    assert site_sheet["J2"].value == "已删除"
    assert site_sheet["H2"].number_format == EXCEL_DATETIME_FORMAT
    assert site_sheet["B2"].hyperlink.target == "https://news.example.com/a"
    assert workbook["总统计"]["F2"].value == "√"
    assert workbook["统计汇总"]["C2"].number_format == EXCEL_DATETIME_FORMAT


@pytest.mark.django_db
def test_export_filters_use_the_same_as_of_for_repost_existence(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    export_as_of = timezone.now()
    record = RepostRecord.objects.create(
        article=article,
        site_name="并发网站",
        site_domain="concurrent.example.com",
        raw_url="https://concurrent.example.com/repost",
        canonical_url="https://concurrent.example.com/repost",
        canonical_url_hash="a" * 64,
        original_url="https://concurrent.example.com/repost",
        normalized_url="https://concurrent.example.com/repost",
        normalized_url_hash="a" * 64,
        repost_title=article.title,
        result_title=article.title,
        first_discovered_at=export_as_of,
        first_found_at=export_as_of,
        last_checked_at=export_as_of,
        last_seen_at=export_as_of,
        data_source="TEST_ONLY",
    )
    RepostRecord.objects.filter(id=record.id).update(created_at=export_as_of + timedelta(seconds=1))

    assert (
        not filtered_articles(GlobalExportFilters(has_repost=True), as_of=export_as_of).filter(id=article.id).exists()
    )
    assert filtered_articles(GlobalExportFilters(has_repost=False), as_of=export_as_of).filter(id=article.id).exists()
    assert (
        not filtered_articles(GlobalExportFilters(site_domain="concurrent.example.com"), as_of=export_as_of)
        .filter(id=article.id)
        .exists()
    )


@pytest.mark.django_db
def test_export_link_totals_are_unique_per_article_and_url(source: Source, operator: User) -> None:
    first = create_source_article(source=source, operator=operator)
    second = Article.objects.create(
        title="第二篇文章",
        normalized_title="第二篇文章",
        published_date=timezone.localdate(),
        published_at=timezone.now(),
        monitoring_status=ArticleMonitoringStatus.COMPLETED,
        created_by=operator,
    )
    now = timezone.now()
    shared_url = "https://shared.example.com/repost"
    for article in (first, second):
        RepostRecord.objects.create(
            article=article,
            site_name="共享网站",
            site_domain="shared.example.com",
            raw_url=shared_url,
            canonical_url=shared_url,
            canonical_url_hash="b" * 64,
            original_url=shared_url,
            normalized_url=shared_url,
            normalized_url_hash="b" * 64,
            repost_title=article.title,
            result_title=article.title,
            first_discovered_at=now,
            first_found_at=now,
            last_checked_at=now,
            last_seen_at=now,
            data_source="TEST_ONLY",
        )

    content, _ = build_global_repost_workbook(GlobalExportFilters(site_domain="shared.example.com"))
    workbook = load_workbook(BytesIO(content))
    summary = workbook["统计汇总"]
    summary_values = {summary.cell(row, 1).value: summary.cell(row, 2).value for row in range(2, 7)}
    assert summary_values["转载链接总数"] == 2
    assert summary.cell(9, 4).value == 2


@pytest.mark.django_db
@override_settings(
    ARTICLE_SEARCH_SCHEDULE_MINUTES=(0, 15, 30, 60, 120, 240, 480),
    ARTICLE_SEARCH_REPEAT_MINUTES=720,
)
def test_search_schedule_repeats_every_twelve_hours_after_eight_hours(source: Source, operator: User) -> None:
    article = create_source_article(source=source, operator=operator)
    started = timezone.now().replace(second=0, microsecond=0)
    article.monitor_started_at = started
    article.monitor_until = started + timedelta(days=7)

    assert _next_search_time(article, started + timedelta(hours=8)) == started + timedelta(hours=20)
    assert _next_search_time(article, started + timedelta(hours=19)) == started + timedelta(hours=20)
    assert _next_search_time(article, started + timedelta(hours=20)) == started + timedelta(hours=32)


INVALID_SHEET_CHARACTERS_FOR_TEST = __import__("re").compile(r"[:\\/?*\[\]]")


def test_sheet_name_sanitization_handles_collisions() -> None:
    used = {"数据", "总统计", "统计汇总"}
    first = sanitize_excel_sheet_name("网站:/名称", used)
    second = sanitize_excel_sheet_name("网站__名称", used)
    assert first == "网站__名称"
    assert second == "网站__名称_2"
