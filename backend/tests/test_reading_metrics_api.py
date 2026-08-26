from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.articles.models import Article, ArticleMonitoringStatus, ArticleStatus
from apps.articles.services import normalize_title
from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.models import OwnedChannel, OwnedChannelType, ReadingMetricObservation, Source
from apps.sources.reading_metrics import collect_due_reading_metrics, query_reading_metric_provider
from apps.sources.token_services import create_source_token


@pytest.fixture
def source(db: object) -> Source:
    return Source.objects.create(
        code="READING_TEST",
        name="Reading test source",
        base_url="https://source.example.com/",
        is_active=True,
    )


@pytest.fixture
def operator(db: object) -> User:
    return User.objects.create_user(
        username="reading-operator",
        password="A-strong-test-password-1",
        role=Role.OPERATOR,
    )


@pytest.fixture
def owned_record(source: Source, operator: User) -> RepostRecord:
    now = timezone.now()
    title = "Reading metric known owned article"
    article = Article.objects.create(
        source=source,
        source_item_key="reading-metric-source-item",
        title=title,
        normalized_title=normalize_title(title),
        published_date=now.date(),
        published_at=now,
        original_url="https://source.example.com/articles/owned",
        source_platform=source.name,
        status=ArticleStatus.ACTIVE,
        monitoring_status=ArticleMonitoringStatus.ACTIVE,
        monitor_started_at=now,
        monitor_until=now + timedelta(days=7),
        retention_until=now + timedelta(days=365),
        created_by=operator,
    )
    channel = OwnedChannel.objects.create(
        code="READING_OWNED",
        name="Reading owned channel",
        channel_type=OwnedChannelType.PLATFORM_ACCOUNT,
        match_rules={"platform_domains": ["owned.example.com"]},
    )
    url = "https://owned.example.com/articles/owned"
    url_hash = sha256(url.encode("utf-8")).hexdigest()
    return RepostRecord.objects.create(
        article=article,
        site_name=channel.name,
        site_domain="owned.example.com",
        raw_url=url,
        canonical_url=url,
        canonical_url_hash=url_hash,
        original_url=url,
        normalized_url=url,
        normalized_url_hash=url_hash,
        repost_title=title,
        result_title=title,
        content_relation=ContentRelation.OWNED,
        owned_channel=channel,
        first_discovered_at=now,
        first_found_at=now,
        last_checked_at=now,
        data_source="TEST",
    )


@pytest.mark.django_db
def test_reading_metric_worker_lists_owned_publication_tasks(
    source: Source, operator: User, owned_record: RepostRecord
) -> None:
    source_token = create_source_token(source=source, name="reading-worker", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")

    response = client.get("/api/v1/reading-metrics/tasks")

    assert response.status_code == 200
    tasks = response.json()["data"]["tasks"]
    assert tasks[0]["id"] == owned_record.id
    assert tasks[0]["article_title"] == owned_record.article.title
    assert tasks[0]["url"] == owned_record.canonical_url


@pytest.mark.django_db
def test_reading_metric_worker_submits_observation_and_page_api_reads_it(
    source: Source, operator: User, owned_record: RepostRecord
) -> None:
    source_token = create_source_token(source=source, name="reading-worker", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")

    response = client.post(
        "/api/v1/reading-metrics/observations",
        {"observations": [{"publication_id": owned_record.id, "reading_count": 1234, "status": "SUCCESS"}]},
        format="json",
    )

    assert response.status_code == 201
    assert ReadingMetricObservation.objects.get(repost_record=owned_record).reading_count == 1234

    client.force_authenticate(user=operator)
    page_response = client.get("/api/v1/reading-monitor/owned-publications")
    assert page_response.status_code == 200
    publication = page_response.json()["data"]["publications"][0]
    assert publication["id"] == owned_record.id
    assert publication["reading_count"] == 1234
    assert publication["reading_status"] == "成功"


@pytest.mark.django_db
def test_reading_metric_worker_cannot_submit_for_external_repost(
    source: Source, operator: User, owned_record: RepostRecord
) -> None:
    owned_record.content_relation = ContentRelation.REPOST
    owned_record.save(update_fields=["content_relation"])
    source_token = create_source_token(source=source, name="reading-worker", created_by=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {source_token.plaintext}")

    response = client.post(
        "/api/v1/reading-metrics/observations",
        {"observations": [{"publication_id": owned_record.id, "reading_count": 999, "status": "SUCCESS"}]},
        format="json",
    )

    assert response.status_code == 404
    assert not ReadingMetricObservation.objects.exists()


@pytest.mark.django_db
@override_settings(
    READING_METRIC_BASE_URL="https://approved-metrics.example.com",
    READING_METRIC_COLLECTION_INTERVAL_MINUTES=60,
)
def test_reading_metrics_are_collected_automatically_without_claiming(
    source: Source, operator: User, owned_record: RepostRecord
) -> None:
    with patch("apps.sources.reading_metrics.httpx.post") as http_post:
        http_post.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"title": owned_record.article.title, "reading_count": 456}]},
        )

        result = collect_due_reading_metrics()

    assert result == {
        "status": "自动检测成功",
        "selected": 1,
        "created": 1,
        "success": 1,
        "not_found": 0,
        "failed": 0,
    }
    observation = ReadingMetricObservation.objects.get(repost_record=owned_record)
    assert observation.reading_count == 456
    assert observation.source == source

    with patch("apps.sources.reading_metrics.httpx.post") as http_post:
        repeated = collect_due_reading_metrics()
    assert repeated["selected"] == 0
    http_post.assert_not_called()


@pytest.mark.django_db
@override_settings(READING_METRIC_BASE_URL="http://approved-internal-metrics")
def test_reading_metrics_match_the_provider_count_by_concrete_publication_url(
    source: Source, operator: User, owned_record: RepostRecord
) -> None:
    first_url = "https://www.toutiao.com/item/7594407547390493238/"
    second_url = "https://www.sohu.com/a/975237356_135869"
    first_hash = sha256(first_url.encode("utf-8")).hexdigest()
    second_hash = sha256(second_url.encode("utf-8")).hexdigest()
    owned_record.raw_url = first_url
    owned_record.canonical_url = first_url
    owned_record.canonical_url_hash = first_hash
    owned_record.original_url = first_url
    owned_record.normalized_url = first_url
    owned_record.normalized_url_hash = first_hash
    owned_record.save(
        update_fields=[
            "raw_url",
            "canonical_url",
            "canonical_url_hash",
            "original_url",
            "normalized_url",
            "normalized_url_hash",
        ]
    )
    second_record = RepostRecord.objects.create(
        article=owned_record.article,
        site_name="搜狐",
        site_domain="sohu.com",
        raw_url=second_url,
        canonical_url=second_url,
        canonical_url_hash=second_hash,
        original_url=second_url,
        normalized_url=second_url,
        normalized_url_hash=second_hash,
        repost_title=owned_record.article.title,
        result_title=owned_record.article.title,
        content_relation=ContentRelation.OWNED,
        owned_channel=owned_record.owned_channel,
        first_discovered_at=timezone.now(),
        first_found_at=timezone.now(),
        last_checked_at=timezone.now(),
        data_source="TEST",
    )

    with patch("apps.sources.reading_metrics.httpx.post") as http_post:
        http_post.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "data": {
                    owned_record.article.title: [
                        {"platform": "今日头条", "url": first_url, "count": 76},
                        {"platform": "搜狐", "url": second_url, "count": 1878},
                    ]
                }
            },
        )
        metrics, provider_status = query_reading_metric_provider([owned_record, second_record])

    assert provider_status == "自动检测成功"
    assert metrics[owned_record.id].reading_count == 76
    assert metrics[second_record.id].reading_count == 1878
