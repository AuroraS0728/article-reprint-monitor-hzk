from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from time import sleep
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.articles.models import Article, ArticleMonitoringStatus, ArticleStatus
from apps.articles.services import ArticleDuplicateError, create_approved_duplicate, create_standard_article
from apps.audit.models import OperationLog
from apps.sources.models import ArticleIngestConflict, ArticleIngestConflictStatus, Source
from apps.sources.token_services import create_source_token

from .test_article_platform import client_for, make_xlsx


def article_data(*, title: str = "同日同标题", published_date: date = date(2026, 8, 11)) -> dict[str, object]:
    return {"title": title, "published_date": published_date}


def source_and_client(*, administrator: User) -> tuple[Source, APIClient]:
    source, _ = Source.objects.update_or_create(
        code="WEEKLYONSTOCK",
        defaults={
            "name": "证券市场周刊",
            "base_url": "https://www.weeklyonstock.com/",
            "is_active": True,
        },
    )
    token = create_source_token(source=source, name="duplicate-tests", created_by=administrator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.plaintext}")
    return source, client


def ingest_payload(*, url: str, published_at: object, title: str = "Source 重复标题") -> dict[str, object]:
    return {
        "title": title,
        "author": "测试作者",
        "published_at": published_at,
        "original_url": url,
    }


@pytest.mark.django_db(transaction=True)
def test_concurrent_standard_creation_only_creates_one_slot_zero(operator: User) -> None:
    barrier = Barrier(2)

    def create_one() -> str:
        close_old_connections()
        try:
            creator = User.objects.get(pk=operator.pk)
            barrier.wait(timeout=10)
            for attempt in range(3):
                try:
                    create_standard_article(data=article_data(title="并发标题"), created_by=creator)
                    return "created"
                except ArticleDuplicateError:
                    return "duplicate"
                except OperationalError:
                    if attempt == 2:
                        raise
                    sleep(0.05)
            raise AssertionError("unreachable")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _value: create_one(), range(2)))

    assert results == ["created", "duplicate"]
    rows = Article.objects.filter(normalized_title="并发标题", published_date=date(2026, 8, 11))
    assert list(rows.values_list("duplicate_slot", flat=True)) == [0]


@pytest.mark.django_db
def test_database_rejects_two_direct_slot_zero_articles(operator: User) -> None:
    values = {
        "title": "直接插入重复",
        "normalized_title": "直接插入重复",
        "published_date": date(2026, 8, 11),
        "duplicate_slot": 0,
        "created_by": operator,
    }
    Article.objects.create(**values)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Article.objects.create(**values)


@pytest.mark.django_db
def test_admin_approved_duplicates_receive_sequential_slots_and_metadata(administrator: User, operator: User) -> None:
    create_standard_article(data=article_data(), created_by=operator)
    first = create_approved_duplicate(
        data=article_data(), approved_by=administrator, duplicate_reason="确认为第二篇独立文章"
    )
    second = create_approved_duplicate(
        data=article_data(), approved_by=administrator, duplicate_reason="确认为第三篇独立文章"
    )

    assert [first.duplicate_slot, second.duplicate_slot] == [1, 2]
    assert first.duplicate_approved_by == administrator
    assert first.duplicate_approved_at is not None
    assert first.duplicate_reason == "确认为第二篇独立文章"


@pytest.mark.django_db
def test_bulk_paste_returns_created_and_duplicate_row_states(operator: User) -> None:
    response = client_for(operator).post(
        "/api/v1/articles/bulk-paste",
        {"articles": [article_data(title="批量重复"), article_data(title="批量重复")]},
        format="json",
    )
    assert response.status_code == 201
    assert [row["status"] for row in response.json()["data"]["results"]] == ["created", "duplicate"]
    assert Article.objects.filter(normalized_title="批量重复").count() == 1


@pytest.mark.django_db
def test_excel_admin_confirmation_really_creates_approved_duplicate(administrator: User, operator: User) -> None:
    create_standard_article(
        data=article_data(title="Excel 重复", published_date=date(2026, 8, 6)),
        created_by=operator,
    )
    uploaded = SimpleUploadedFile(
        "duplicate.xlsx",
        make_xlsx(title="Excel 重复"),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    preview = client_for(operator).post("/api/v1/article-imports", {"file": uploaded}, format="multipart")
    assert preview.status_code == 201
    assert preview.json()["data"]["duplicate_rows"] == 1
    assert Article.objects.filter(normalized_title="Excel 重复").count() == 1

    confirmed = client_for(administrator).post(
        f"/api/v1/article-imports/{preview.json()['data']['id']}/confirm",
        {
            "confirm_duplicate_rows": [2],
            "duplicate_reasons": {"2": "Excel 中确认为不同文章"},
        },
        format="json",
    )
    assert confirmed.status_code == 200
    duplicate = Article.objects.get(normalized_title="Excel 重复", duplicate_slot=1)
    assert duplicate.duplicate_approved_by == administrator
    assert duplicate.duplicate_reason == "Excel 中确认为不同文章"
    assert OperationLog.objects.filter(action_type="ARTICLE_DUPLICATE_APPROVED", target_id=str(duplicate.id)).exists()


@pytest.mark.django_db
def test_archived_article_still_blocks_standard_creation(operator: User) -> None:
    existing = create_standard_article(data=article_data(title="已归档重复"), created_by=operator)
    existing.status = ArticleStatus.ARCHIVED
    existing.save(update_fields=["status"])
    response = client_for(operator).post(
        "/api/v1/articles",
        {"title": "已归档重复", "published_date": "2026-08-11"},
        format="json",
    )
    assert response.status_code == 400
    assert Article.objects.filter(normalized_title="已归档重复").count() == 1


@pytest.mark.django_db
def test_source_url_idempotency_and_different_url_conflict_are_persistent(administrator: User) -> None:
    _source, client = source_and_client(administrator=administrator)
    published_at = timezone.now().replace(microsecond=0)
    first_payload = ingest_payload(
        url="https://www.weeklyonstock.com/article/source-a",
        published_at=published_at.isoformat(),
    )
    with patch("apps.sources.tasks.search_article_reposts.delay"):
        first = client.post("/api/v1/source-ingest/articles", first_payload, format="json")
        repeated = client.post("/api/v1/source-ingest/articles", first_payload, format="json")
    assert first.status_code == 201
    assert repeated.status_code == 200
    assert Article.objects.count() == 1

    article = Article.objects.get()
    article.status = ArticleStatus.ARCHIVED
    article.save(update_fields=["status"])
    assert client.post("/api/v1/source-ingest/articles", first_payload, format="json").status_code == 200
    assert ArticleIngestConflict.objects.count() == 0

    conflict_payload = ingest_payload(
        url="https://www.weeklyonstock.com/article/source-b",
        published_at=published_at.isoformat(),
    )
    first_conflict = client.post("/api/v1/source-ingest/articles", conflict_payload, format="json")
    repeated_conflict = client.post("/api/v1/source-ingest/articles", conflict_payload, format="json")
    assert first_conflict.status_code == 202
    assert first_conflict.json()["data"]["reason_code"] == "DUPLICATE_REVIEW_REQUIRED"
    assert repeated_conflict.status_code == 202
    assert Article.objects.count() == 1
    assert ArticleIngestConflict.objects.count() == 1
    assert OperationLog.objects.filter(action_type="SOURCE_INGEST_CONFLICT_CREATED").count() == 1


def prepare_source_conflict(*, administrator: User, days_old: int) -> tuple[ArticleIngestConflict, int]:
    _source, client = source_and_client(administrator=administrator)
    published_at = (timezone.now() - timedelta(days=days_old)).replace(microsecond=0)
    with patch("apps.sources.tasks.search_article_reposts.delay"):
        first = client.post(
            "/api/v1/source-ingest/articles",
            ingest_payload(
                url=f"https://www.weeklyonstock.com/article/base-{days_old}",
                published_at=published_at.isoformat(),
            ),
            format="json",
        )
    assert first.status_code == 201
    conflict_response = client.post(
        "/api/v1/source-ingest/articles",
        ingest_payload(
            url=f"https://www.weeklyonstock.com/article/conflict-{days_old}",
            published_at=published_at.isoformat(),
        ),
        format="json",
    )
    assert conflict_response.status_code == 202
    return (
        ArticleIngestConflict.objects.get(pk=conflict_response.json()["data"]["conflict_id"]),
        first.json()["data"]["article_id"],
    )


@pytest.mark.django_db
def test_admin_approves_source_conflict_with_remaining_original_monitoring_window(administrator: User) -> None:
    conflict, _existing_id = prepare_source_conflict(administrator=administrator, days_old=1)
    with patch("apps.sources.tasks.search_article_reposts.delay"):
        response = client_for(administrator).post(
            f"/api/v1/source-ingest-conflicts/{conflict.id}/review",
            {"action": "APPROVED_AS_NEW", "reason": "确认为另一篇来源文章"},
            format="json",
        )
    assert response.status_code == 200
    conflict.refresh_from_db()
    article = conflict.created_article
    assert conflict.status == ArticleIngestConflictStatus.APPROVED_AS_NEW
    assert article is not None
    assert article.duplicate_slot == 1
    assert article.monitoring_status == ArticleMonitoringStatus.ACTIVE
    assert article.monitor_until == article.published_at + timedelta(days=7)
    assert article.duplicate_approved_by == administrator
    assert OperationLog.objects.filter(action_type="SOURCE_INGEST_CONFLICT_REVIEWED").exists()


@pytest.mark.django_db
def test_admin_approval_after_original_window_does_not_restart_seven_days(administrator: User) -> None:
    conflict, _existing_id = prepare_source_conflict(administrator=administrator, days_old=8)
    response = client_for(administrator).post(
        f"/api/v1/source-ingest-conflicts/{conflict.id}/review",
        {"action": "APPROVED_AS_NEW", "reason": "历史文章确认为独立文章"},
        format="json",
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    article = conflict.created_article
    assert article is not None
    assert article.monitoring_status == ArticleMonitoringStatus.COMPLETED
    assert article.monitor_started_at is None
    assert article.next_search_at is None
    assert article.monitor_until == article.published_at + timedelta(days=7)


@pytest.mark.django_db
def test_admin_links_source_conflict_without_creating_article(administrator: User) -> None:
    conflict, existing_id = prepare_source_conflict(administrator=administrator, days_old=1)
    count_before = Article.objects.count()
    response = client_for(administrator).post(
        f"/api/v1/source-ingest-conflicts/{conflict.id}/review",
        {"action": "LINKED_TO_EXISTING", "reason": "确认是已有文章", "article_id": existing_id},
        format="json",
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    assert conflict.status == ArticleIngestConflictStatus.LINKED_TO_EXISTING
    assert conflict.linked_article_id == existing_id
    assert Article.objects.count() == count_before
    assert OperationLog.objects.filter(action_type="ARTICLE_DUPLICATE_LINKED").exists()
