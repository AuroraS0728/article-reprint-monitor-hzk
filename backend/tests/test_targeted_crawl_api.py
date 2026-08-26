from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.articles.models import Article, ArticleMonitoringStatus, ArticleStatus
from apps.articles.services import normalize_title
from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.models import (
    AutomaticRepostSite,
    SearchRun,
    SearchRunStatus,
    Source,
    TargetedCrawlDispatchState,
    TargetedCrawlTask,
    TargetedCrawlTaskStatus,
)
from apps.sources.services import due_targeted_crawl_tasks, targeted_crawl_dispatch_state
from apps.sources.token_services import create_source_token


@pytest.fixture
def source(db: object) -> Source:
    return Source.objects.create(
        code="TARGETED_TEST",
        name="Targeted test source",
        base_url="https://source.example.com/",
        is_active=True,
    )


@pytest.fixture
def operator(db: object) -> User:
    return User.objects.create_user(
        username="targeted-operator",
        password="A-strong-test-password-1",
        role=Role.OPERATOR,
    )


@pytest.fixture
def article(source: Source, operator: User) -> Article:
    now = timezone.now()
    title = "Targeted crawl known repost title"
    return Article.objects.create(
        source=source,
        source_item_key="targeted-crawl-item",
        title=title,
        normalized_title=normalize_title(title),
        published_date=now.date(),
        published_at=now,
        original_url="https://source.example.com/articles/known-repost",
        source_platform=source.name,
        status=ArticleStatus.ACTIVE,
        monitoring_status=ArticleMonitoringStatus.ACTIVE,
        monitor_started_at=now,
        monitor_until=now + timedelta(days=7),
        retention_until=now + timedelta(days=365),
        created_by=operator,
    )


@pytest.mark.django_db
def test_targeted_crawl_claim_submit_candidates_and_complete(source: Source, operator: User, article: Article) -> None:
    source_token = create_source_token(source=source, name="local-browser", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")

    task_response = client.get("/api/v1/targeted-crawl/tasks")
    assert task_response.status_code == 200
    task = task_response.json()["data"]["tasks"][0]
    assert task["article_id"] == article.id
    assert task["query"] == article.title
    assert task["dispatch_state"] == TargetedCrawlDispatchState.FIRST_SCAN_READY
    assert task["first_scan_done"] is False

    claim_response = client.post(f"/api/v1/targeted-crawl/tasks/{task['id']}/claim", {}, format="json")
    assert claim_response.status_code == 201
    claim = claim_response.json()["data"]
    assert claim["run_id"] > 0
    assert len(claim["claim_token"]) >= 32

    candidate_response = client.post(
        "/api/v1/targeted-crawl/candidates",
        {
            "task_id": task["id"],
            "run_id": claim["run_id"],
            "claim_token": claim["claim_token"],
            "candidates": [
                {
                    "title": article.title,
                    "url": "https://external.example.net/repost/42?utm_source=search",
                    "site_name": "External news",
                    "published_at": (article.published_at + timedelta(minutes=1)).isoformat(),
                    "search_phase": "EXACT",
                }
            ],
        },
        format="json",
    )
    assert candidate_response.status_code == 201
    candidate = candidate_response.json()["data"][0]
    assert candidate["canonical_url"] == "https://external.example.net/repost/42"
    assert candidate["content_relation"] == ContentRelation.REPOST

    complete_response = client.post(
        "/api/v1/targeted-crawl/runs",
        {
            "task_id": task["id"],
            "run_id": claim["run_id"],
            "claim_token": claim["claim_token"],
            "status": "SUCCESS",
        },
        format="json",
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["data"]["run"]["status"] == SearchRunStatus.SUCCESS
    assert complete_response.json()["data"]["run"]["repost_count"] == 1
    completed_task = TargetedCrawlTask.objects.get(pk=task["id"])
    assert completed_task.first_scan_done is True
    assert completed_task.first_scan_completed_at is not None
    assert targeted_crawl_dispatch_state(completed_task) == TargetedCrawlDispatchState.WAIT_NEXT_SCAN
    assert RepostRecord.objects.filter(article=article, content_relation=ContentRelation.REPOST).exists()

    replay_response = client.post(
        "/api/v1/targeted-crawl/candidates",
        {
            "task_id": task["id"],
            "run_id": claim["run_id"],
            "claim_token": claim["claim_token"],
            "candidates": [{"title": article.title, "url": "https://external.example.net/repost/43"}],
        },
        format="json",
    )
    assert replay_response.status_code == 403
    assert TargetedCrawlTask.objects.get(pk=task["id"]).last_run_id == claim["run_id"]
    assert SearchRun.objects.get(pk=claim["run_id"]).candidate_count == 1


@pytest.mark.django_db
def test_targeted_crawl_partial_success_releases_task(source: Source, operator: User, article: Article) -> None:
    source_token = create_source_token(source=source, name="partial-browser", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")

    task = client.get("/api/v1/targeted-crawl/tasks").json()["data"]["tasks"][0]
    claim = client.post(f"/api/v1/targeted-crawl/tasks/{task['id']}/claim", {}, format="json").json()["data"]

    complete_response = client.post(
        "/api/v1/targeted-crawl/runs",
        {
            "task_id": task["id"],
            "run_id": claim["run_id"],
            "claim_token": claim["claim_token"],
            "status": "PARTIAL_SUCCESS",
            "matched_count": 0,
            "submitted_count": 0,
            "failed_count": 0,
            "platform_results": [
                {
                    "platform_code": "SINA_FINANCE",
                    "platform_name": "新浪财经",
                    "status": "SUCCESS",
                    "crawl_status": "NO_PLATFORM_DUE",
                    "matched_count": 0,
                }
            ],
        },
        format="json",
    )

    assert complete_response.status_code == 200
    assert complete_response.json()["data"]["run"]["status"] == SearchRunStatus.SUCCESS
    completed_task = TargetedCrawlTask.objects.get(pk=task["id"])
    assert completed_task.status == TargetedCrawlTaskStatus.PENDING
    assert completed_task.claim_token_hash == ""
    assert completed_task.first_scan_done is True


@pytest.mark.django_db
def test_targeted_crawl_first_scan_overrides_stale_incremental_schedule(
    source: Source, operator: User, article: Article
) -> None:
    """A just-ingested article must not wait for an old schedule timestamp."""

    delayed_task = TargetedCrawlTask.objects.create(
        source=source,
        article=article,
        query=article.title,
        next_available_at=timezone.now() + timedelta(hours=2),
        first_scan_done=False,
    )

    due_tasks = due_targeted_crawl_tasks(source=source, limit=5)

    delayed_task.refresh_from_db()
    assert [task.id for task in due_tasks] == [delayed_task.id]
    assert delayed_task.next_available_at <= timezone.now()
    assert targeted_crawl_dispatch_state(delayed_task) == TargetedCrawlDispatchState.FIRST_SCAN_READY


@pytest.mark.django_db
def test_targeted_crawl_does_not_return_completed_article_task(source: Source, article: Article) -> None:
    article.monitoring_status = ArticleMonitoringStatus.COMPLETED
    article.monitor_until = timezone.now() - timedelta(minutes=1)
    article.save(update_fields=["monitoring_status", "monitor_until", "updated_at"])
    stale_task = TargetedCrawlTask.objects.create(
        source=source,
        article=article,
        query=article.title,
        next_available_at=timezone.now() - timedelta(minutes=1),
        first_scan_done=False,
    )

    assert targeted_crawl_dispatch_state(stale_task) == TargetedCrawlDispatchState.MONITORING_ENDED
    assert due_targeted_crawl_tasks(source=source, limit=5) == []


@pytest.mark.django_db
def test_targeted_crawl_confirmed_repost_does_not_stop_due_scan(
    source: Source, operator: User, article: Article
) -> None:
    """Confirmed reposts do not become a task-level skip condition."""

    task = TargetedCrawlTask.objects.create(
        source=source,
        article=article,
        query=article.title,
        first_scan_done=True,
        next_available_at=timezone.now() - timedelta(minutes=1),
    )
    RepostRecord.objects.create(
        article=article,
        site_name="Existing external site",
        site_domain="existing.example.net",
        original_url="https://existing.example.net/repost",
        normalized_url="https://existing.example.net/repost",
        normalized_url_hash="e" * 64,
        repost_title=article.title,
        first_discovered_at=timezone.now(),
        last_checked_at=timezone.now(),
        data_source="TEST",
        content_relation=ContentRelation.REPOST,
    )

    assert targeted_crawl_dispatch_state(task) == TargetedCrawlDispatchState.READY
    assert [item.id for item in due_targeted_crawl_tasks(source=source, limit=5)] == [task.id]


@pytest.mark.django_db
def test_targeted_crawl_retains_high_similarity_candidates_without_publication_time(
    source: Source, operator: User, article: Article
) -> None:
    source_token = create_source_token(source=source, name="candidate-filter", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")
    task = client.get("/api/v1/targeted-crawl/tasks").json()["data"]["tasks"][0]
    claim = client.post(f"/api/v1/targeted-crawl/tasks/{task['id']}/claim", {}, format="json").json()["data"]

    response = client.post(
        "/api/v1/targeted-crawl/candidates",
        {
            "task_id": task["id"],
            "run_id": claim["run_id"],
            "claim_token": claim["claim_token"],
            "candidates": [
                {"title": article.title, "url": "https://external.example.net/no-date"},
                {
                    "title": article.title,
                    "url": "https://external.example.net/same-date",
                    "published_at": article.published_at.isoformat(),
                },
                {
                    "title": "与原创标题无关",
                    "url": "https://external.example.net/unrelated",
                    "published_at": (article.published_at + timedelta(minutes=1)).isoformat(),
                },
                {
                    "title": article.title,
                    "url": "https://external.example.net/retained",
                    "published_at": (article.published_at + timedelta(minutes=1)).isoformat(),
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert [item["canonical_url"] for item in response.json()["data"]] == [
        "https://external.example.net/no-date",
        "https://external.example.net/same-date",
        "https://external.example.net/retained",
    ]
    assert SearchRun.objects.get(pk=claim["run_id"]).candidates.count() == 3


@pytest.mark.django_db
def test_targeted_crawl_auto_confirms_configured_media_site_at_candidate_threshold(
    source: Source, operator: User, article: Article
) -> None:
    AutomaticRepostSite.objects.create(
        code="TARGETED_AUTO_MEDIA",
        name="Targeted automatic media",
        domains=["targeted-media.example.com"],
    )
    token = create_source_token(source=source, name="auto-media", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.plaintext}")
    task = client.get("/api/v1/targeted-crawl/tasks").json()["data"]["tasks"][0]
    claim = client.post(f"/api/v1/targeted-crawl/tasks/{task['id']}/claim", {}, format="json").json()["data"]

    with patch("apps.sources.services.fuzz.ratio", return_value=85.0):
        response = client.post(
            "/api/v1/targeted-crawl/candidates",
            {
                "task_id": task["id"],
                "run_id": claim["run_id"],
                "claim_token": claim["claim_token"],
                "candidates": [
                    {
                        "title": "Targeted crawl known repost title report",
                        "url": "https://targeted-media.example.com/repost",
                    }
                ],
            },
            format="json",
        )

    assert response.status_code == 201
    candidate = response.json()["data"][0]
    assert candidate["content_relation"] == ContentRelation.REPOST
    assert candidate["reason_code"] == "AUTO_REPOST_SITE_DOMAIN:TARGETED_AUTO_MEDIA"
    assert RepostRecord.objects.filter(article=article, content_relation=ContentRelation.REPOST).exists()


@pytest.mark.django_db
def test_targeted_crawl_cannot_claim_another_source_task(source: Source, operator: User, article: Article) -> None:
    other_source = Source.objects.create(
        code="TARGETED_OTHER",
        name="Other source",
        base_url="https://other.example.com/",
        is_active=True,
    )
    source_token = create_source_token(source=source, name="first", created_by=operator)
    other_token = create_source_token(source=other_source, name="second", created_by=operator)
    first = APIClient()
    first.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")
    task_id = first.get("/api/v1/targeted-crawl/tasks").json()["data"]["tasks"][0]["id"]

    second = APIClient()
    second.credentials(HTTP_AUTHORIZATION=f"Bearer {other_token.plaintext}")
    denied = second.post(f"/api/v1/targeted-crawl/tasks/{task_id}/claim", {}, format="json")
    assert denied.status_code == 403


@pytest.mark.django_db
def test_manual_article_is_bound_to_single_source_and_is_first_scan_ready(source: Source, operator: User) -> None:
    source_token = create_source_token(source=source, name="manual-article-source", created_by=operator)
    client = APIClient()
    client.force_authenticate(user=operator)
    response = client.post(
        "/api/v1/articles",
        {"title": "手工录入后应立即进入监测", "published_date": timezone.localdate().isoformat()},
        format="json",
    )
    assert response.status_code == 201
    created = Article.objects.get(pk=response.json()["id"])
    assert created.source_id == source.id
    assert created.monitoring_status == ArticleMonitoringStatus.ACTIVE
    assert created.monitor_until is not None
    assert created.next_search_at is not None

    worker = APIClient()
    worker.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")
    tasks = worker.get("/api/v1/targeted-crawl/tasks").json()["data"]["tasks"]
    assert any(item["article_id"] == created.id for item in tasks)


@pytest.mark.django_db
def test_source_worker_backfills_preexisting_unbound_manual_article(source: Source, operator: User) -> None:
    now = timezone.now()
    legacy = Article.objects.create(
        title="旧版手工文章也要进入监测",
        normalized_title=normalize_title("旧版手工文章也要进入监测"),
        published_date=now.date(),
        status=ArticleStatus.ACTIVE,
        created_by=operator,
    )

    tasks = due_targeted_crawl_tasks(source=source, limit=5)

    legacy.refresh_from_db()
    assert legacy.source_id == source.id
    assert legacy.monitoring_status == ArticleMonitoringStatus.ACTIVE
    assert any(task.article_id == legacy.id for task in tasks)
