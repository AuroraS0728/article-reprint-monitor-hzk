from datetime import date, timedelta

import pytest
from django.conf import LazySettings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.articles.models import Article
from apps.monitoring.batch_services import create_batch
from apps.monitoring.models import BatchStatus, DetectionResult, PlatformDetectionStatus, SnapshotType
from apps.monitoring.services import SearchOutcome, evaluate_detection
from apps.monitoring.snapshot_services import create_status_snapshot, matrix_data_as_of
from apps.platforms.models import Platform, PlatformStatus
from apps.reports.services import safe_excel_text
from tests.test_article_platform import client_for, make_xlsx


class OutcomeAdapter:
    """Deterministic outcome adapter used only to verify state mapping rules."""

    def __init__(self, outcome: SearchOutcome) -> None:
        self.outcome = outcome

    def search_exact_title(self, *, article: Article, platform: Platform) -> SearchOutcome:
        return self.outcome


def source_article(*, operator: User, title: str = "Acceptance article") -> Article:
    return Article.objects.create(
        title=title,
        normalized_title=title,
        published_date=date(2026, 8, 6),
        created_by=operator,
    )


def platform(*, code: str = "ACCEPTANCE_PLATFORM") -> Platform:
    return Platform.objects.create(code=code, name=code, status=PlatformStatus.ENABLED)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reason_code",
    [
        "REQUEST_TIMEOUT",
        "LOGIN_REQUIRED",
        "CAPTCHA_DETECTED",
        "PARSE_FAILED",
        "NETWORK_ERROR",
        "SEARCH_UNCONFIRMED",
    ],
)
def test_all_unconfirmed_failure_kinds_remain_unknown(operator: User, reason_code: str) -> None:
    article = source_article(operator=operator)
    target = platform(code=f"UNKNOWN_{reason_code}")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[target.id],
        created_by=operator,
        idempotency_key=f"acceptance-{reason_code}",
    )
    result = batch.results.get()
    evaluate_detection(
        result=result,
        adapter=OutcomeAdapter(
            SearchOutcome(
                request_success=False,
                completed=False,
                reason_code=reason_code,
                reason_message="unconfirmed test outcome",
                login_required=reason_code == "LOGIN_REQUIRED",
                captcha_detected=reason_code == "CAPTCHA_DETECTED",
            )
        ),
    )
    result.refresh_from_db()
    assert result.status == PlatformDetectionStatus.UNKNOWN
    assert result.reason_code == reason_code


@pytest.mark.django_db
def test_weekly_final_snapshot_uses_final_batch_even_when_completed_after_nominal_cutoff(operator: User) -> None:
    article = source_article(operator=operator)
    target = platform(code="WEEKLY_FINAL_PLATFORM")
    cutoff = timezone.now().replace(hour=7, minute=0, second=0, microsecond=0)
    prior = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[target.id],
        created_by=operator,
        idempotency_key="acceptance-weekly-prior",
    )
    DetectionResult.objects.filter(batch=prior).update(
        status=PlatformDetectionStatus.FOUND,
        completed_at=cutoff - timedelta(minutes=1),
    )
    final = create_batch(
        trigger="WEEKLY_FINAL",
        article_ids=[article.id],
        platform_ids=[target.id],
        created_by=operator,
        idempotency_key="acceptance-weekly-final",
    )
    DetectionResult.objects.filter(batch=final).update(
        status=PlatformDetectionStatus.NOT_FOUND,
        completed_at=cutoff + timedelta(minutes=5),
    )
    final.status = BatchStatus.COMPLETED
    final.completed_at = cutoff + timedelta(minutes=5)
    final.save(update_fields=["status", "completed_at"])

    snapshot = create_status_snapshot(snapshot_type=SnapshotType.WEEKLY, cutoff_at=cutoff, source_batch=final)

    assert snapshot.matrix_data[f"{article.id}:{target.id}"]["status"] == PlatformDetectionStatus.NOT_FOUND


@pytest.mark.django_db
def test_daily_snapshot_is_not_changed_by_later_detection(operator: User) -> None:
    article = source_article(operator=operator)
    target = platform(code="DAILY_FROZEN_PLATFORM")
    cutoff = timezone.now()
    early = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[target.id],
        created_by=operator,
        idempotency_key="acceptance-daily-early",
    )
    DetectionResult.objects.filter(batch=early).update(
        status=PlatformDetectionStatus.NOT_FOUND,
        completed_at=cutoff - timedelta(minutes=1),
    )
    snapshot = create_status_snapshot(snapshot_type=SnapshotType.DAILY, cutoff_at=cutoff)
    later = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[target.id],
        created_by=operator,
        idempotency_key="acceptance-daily-later",
    )
    DetectionResult.objects.filter(batch=later).update(
        status=PlatformDetectionStatus.FOUND,
        completed_at=cutoff + timedelta(minutes=1),
    )

    assert snapshot.matrix_data[f"{article.id}:{target.id}"]["status"] == PlatformDetectionStatus.NOT_FOUND
    current_matrix = matrix_data_as_of(cutoff_at=cutoff)
    assert current_matrix[f"{article.id}:{target.id}"]["status"] == PlatformDetectionStatus.NOT_FOUND


@pytest.mark.django_db
def test_authenticated_write_requires_csrf_token(operator: User) -> None:
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(operator)
    payload = {"title": "CSRF article", "published_date": "2026-08-06"}
    assert client.post("/api/v1/articles", payload, format="json").status_code == 403
    csrf_token = client.get("/api/v1/auth/login").json()["data"]["csrf_token"]
    assert client.post("/api/v1/articles", payload, format="json", HTTP_X_CSRFTOKEN=csrf_token).status_code == 201


@pytest.mark.django_db
def test_article_query_is_parameterized_against_sql_injection(operator: User) -> None:
    client = client_for(operator)
    client.post("/api/v1/articles", {"title": "Safe result", "published_date": "2026-08-06"}, format="json")
    response = client.get("/api/v1/articles?title=' OR 1=1 --")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.django_db
def test_import_path_is_private_and_disallows_path_traversal(operator: User) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    uploaded = SimpleUploadedFile(
        "../../outside.xlsx",
        make_xlsx(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response = client_for(operator).post("/api/v1/article-imports", {"file": uploaded}, format="multipart")
    assert response.status_code == 201
    data = response.json()["data"]
    assert "/" not in data["original_filename"]
    assert "\\" not in data["original_filename"]


@pytest.mark.django_db
def test_cors_does_not_grant_arbitrary_origin_and_viewer_cannot_operate(viewer: User) -> None:
    client = APIClient()
    response = client.get("/api/v1/health/", HTTP_ORIGIN="https://attacker.example")
    assert "Access-Control-Allow-Origin" not in response.headers
    assert (
        client_for(viewer)
        .post("/api/v1/detection-batches", {"article_ids": [1], "platform_ids": [1]}, format="json")
        .status_code
        == 403
    )


@pytest.mark.django_db
def test_brute_force_limit_blocks_correct_password_after_repeated_failures(user: User) -> None:
    client = APIClient(enforce_csrf_checks=False)
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login",
                {"username": "operator", "password": "wrong-password"},
                format="json",
            ).status_code
            == 401
        )
    blocked = client.post(
        "/api/v1/auth/login",
        {"username": "operator", "password": "safe-test-password"},
        format="json",
    )
    assert blocked.status_code != 200


def test_excel_formula_prefixes_are_all_sanitized() -> None:
    assert [safe_excel_text(value) for value in ["=1+1", "+1", "-1", "@name"]] == [
        "'=1+1",
        "'+1",
        "'-1",
        "'@name",
    ]


def test_beat_schedule_contains_required_detection_and_report_jobs(settings: LazySettings) -> None:
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert schedule["schedule-automatic-detection-hourly"]["task"] == "apps.monitoring.tasks.schedule_automatic_batches"
    assert schedule["schedule-weekly-final-detection"]["task"] == "apps.monitoring.tasks.schedule_weekly_final_batch"
    assert schedule["snapshot-daily-status"]["task"] == "apps.monitoring.tasks.create_daily_status_snapshot"
    assert schedule["snapshot-weekly-status"]["task"] == "apps.monitoring.tasks.create_weekly_status_snapshot"
    assert settings.CELERY_TIMEZONE == "Asia/Shanghai"
