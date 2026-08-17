from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.articles.models import Article, ArticleMonitoringStatus, ArticleStatus
from apps.articles.services import normalize_title
from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.models import SearchRun, SearchRunStatus, Source, TargetedCrawlTask
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
