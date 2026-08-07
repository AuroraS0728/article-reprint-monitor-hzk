from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.accounts.models import User
from apps.articles.models import Article
from apps.audit.models import OperationLog
from apps.audit.services import record_audit
from apps.monitoring.batch_services import batch_statistics, create_batch
from apps.monitoring.models import SnapshotType, StatusSnapshot, TaskFailureLog
from apps.monitoring.services import evaluate_detection
from apps.operations.models import MaintenanceStatus
from apps.operations.services import cleanup_expired_data, create_database_backup
from apps.platforms.models import Platform, PlatformStatus
from apps.reports.models import GeneratedReport, ReportType
from apps.reposts.models import RepostRecord
from tests.fixtures.test_adapter import FixtureAdapter
from tests.test_article_platform import client_for


def source_article(*, actor: User, title: str = "manual supplement source") -> Article:
    return Article.objects.create(
        title=title, normalized_title=title, published_date=date(2026, 8, 6), created_by=actor
    )


def source_platform(*, code: str = "MANUAL_PLATFORM") -> Platform:
    return Platform.objects.create(code=code, name=code, status=PlatformStatus.ENABLED)


@pytest.mark.django_db
def test_operator_can_add_manual_repost_and_only_admin_can_invalidate_or_restore(
    operator: User, administrator: User, viewer: User
) -> None:
    article = source_article(actor=operator)
    platform = source_platform()
    payload = {
        "article": article.id,
        "platform": platform.id,
        "repost_url": "https://example.com/repost?utm_source=x",
        "reason": "missed by platform search",
    }
    assert client_for(viewer).post("/api/v1/manual-reposts", payload, format="json").status_code == 403
    created = client_for(operator).post("/api/v1/manual-reposts", payload, format="json")
    assert created.status_code == 201
    record = RepostRecord.objects.get(pk=created.json()["data"]["id"])
    assert record.data_source == "MANUAL_SUPPLEMENT"
    assert record.is_valid is True
    assert record.manual_reason == "missed by platform search"
    assert (
        client_for(operator)
        .post(f"/api/v1/manual-reposts/{record.id}/invalidate", {"reason": "bad"}, format="json")
        .status_code
        == 403
    )
    invalidated = client_for(administrator).post(
        f"/api/v1/manual-reposts/{record.id}/invalidate", {"reason": "verified as incorrect"}, format="json"
    )
    assert invalidated.status_code == 200
    record.refresh_from_db()
    assert record.is_valid is False
    restored = client_for(administrator).post(f"/api/v1/manual-reposts/{record.id}/restore", {}, format="json")
    assert restored.status_code == 200
    record.refresh_from_db()
    assert record.is_valid is True
    assert OperationLog.objects.filter(action_type="MANUAL_REPOST_CREATE", target_id=str(record.id)).exists()
    assert OperationLog.objects.filter(action_type="MANUAL_REPOST_INVALIDATE", target_id=str(record.id)).exists()
    assert OperationLog.objects.filter(action_type="MANUAL_REPOST_RESTORE", target_id=str(record.id)).exists()


@pytest.mark.django_db
def test_valid_manual_repost_enters_batch_statistics_and_invalid_record_does_not(operator: User) -> None:
    article = source_article(actor=operator)
    platform = source_platform(code="MANUAL_STATS_PLATFORM")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="manual-statistics",
    )
    result = batch.results.get()
    evaluate_detection(result=result, adapter=FixtureAdapter(completed=False))
    created = client_for(operator).post(
        "/api/v1/manual-reposts",
        {
            "article": article.id,
            "platform": platform.id,
            "repost_url": "https://example.com/manual",
            "reason": "operator check",
        },
        format="json",
    )
    assert created.status_code == 201
    stats = batch_statistics(batch)
    assert stats["article_repost_rate"] == 1
    assert stats["detection_completion_rate"] == 1
    record = RepostRecord.objects.get(pk=created.json()["data"]["id"])
    record.is_valid = False
    record.save(update_fields=["is_valid"])
    stats = batch_statistics(batch)
    assert stats["article_repost_rate"] == 0
    assert stats["detection_completion_rate"] == 0


@pytest.mark.django_db
def test_platform_runtime_status_tracks_success_and_failure(operator: User) -> None:
    article = source_article(actor=operator)
    platform = source_platform(code="RUNTIME_PLATFORM")
    batch = create_batch(
        trigger="IMMEDIATE",
        article_ids=[article.id],
        platform_ids=[platform.id],
        created_by=operator,
        idempotency_key="runtime",
    )
    result = batch.results.get()
    evaluate_detection(result=result, adapter=FixtureAdapter(completed=False))
    platform.refresh_from_db()
    assert platform.consecutive_failure_count == 1
    assert platform.last_failure_reason == "FIXTURE_UNCONFIRMED"
    evaluate_detection(result=result, adapter=FixtureAdapter(completed=True))
    platform.refresh_from_db()
    assert platform.consecutive_failure_count == 0
    assert platform.last_success_at is not None


@pytest.mark.django_db
def test_audit_redaction_removes_sensitive_values_and_authenticated_urls(administrator: User) -> None:
    request = client_for(administrator).get("/api/v1/auth/me").wsgi_request
    record_audit(
        request,
        action_type="TEST_REDACTION",
        target_type="test",
        after_data={
            "password": "do-not-store",
            "smtp_authorization_code": "do-not-store",
            "nested": {"AccessKey": "do-not-store"},
            "url": "https://example.test/path?token=do-not-store",
            "error": "connection failed: password=do-not-store",
        },
    )
    data = OperationLog.objects.get(action_type="TEST_REDACTION").after_data
    serialized = str(data)
    assert "do-not-store" not in serialized
    assert data["url"] == "[REDACTED_URL]"


@pytest.mark.django_db
def test_cleanup_removes_expired_report_files_and_task_logs(operator: User) -> None:
    snapshot = StatusSnapshot.objects.create(snapshot_type=SnapshotType.DAILY, cutoff_at=timezone.now(), matrix_data={})
    report = GeneratedReport.objects.create(
        report_type=ReportType.DAILY,
        report_date=date(2025, 1, 1),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 1),
        snapshot=snapshot,
        generated_by=operator,
        report_file=ContentFile(b"report", name="expired.xlsx"),
        file_sha256="a" * 64,
    )
    TaskFailureLog.objects.create(task_name="expired", error_type="Error", message="old log")
    old = timezone.now() - timedelta(days=31)
    GeneratedReport.objects.filter(pk=report.id).update(generated_at=old)
    TaskFailureLog.objects.update(created_at=old)
    run = cleanup_expired_data()
    report.refresh_from_db()
    assert report.report_file.name == ""
    assert not TaskFailureLog.objects.exists()
    assert run.status == MaintenanceStatus.SUCCEEDED
    assert run.details["report_files_deleted"] == 1


@pytest.mark.django_db
def test_database_backup_uses_private_file_and_never_stores_password() -> None:
    with patch("apps.operations.services.subprocess.run", return_value=SimpleNamespace(stdout=b"-- private sql")):
        backup = create_database_backup()
    assert backup.status == MaintenanceStatus.SUCCEEDED
    assert backup.backup_file.name.startswith("database-backups/")
    assert backup.size_bytes == len(b"-- private sql")
    assert "MYSQL_PWD" not in backup.error_message


@pytest.mark.django_db
def test_runtime_maintenance_apis_are_administrator_only(administrator: User, operator: User, viewer: User) -> None:
    for endpoint in ["/api/v1/runtime-status", "/api/v1/task-failure-logs", "/api/v1/database-backups"]:
        assert client_for(viewer).get(endpoint).status_code == 403
        assert client_for(operator).get(endpoint).status_code == 403
        assert client_for(administrator).get(endpoint).status_code == 200
    updated = client_for(administrator).patch(
        "/api/v1/system-runtime-configuration", {"maintenance_enabled": False}, format="json"
    )
    assert updated.status_code == 200
    assert OperationLog.objects.filter(action_type="SYSTEM_RUNTIME_CONFIGURATION_UPDATE").exists()


def test_maintenance_and_backup_are_scheduled_in_shanghai_timezone(settings: object) -> None:
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert schedule["cleanup-expired-data"]["task"] == "apps.operations.tasks.cleanup_expired_data_task"
    assert schedule["database-backup-daily"]["task"] == "apps.operations.tasks.create_database_backup_task"
    assert settings.CELERY_TIMEZONE == "Asia/Shanghai"
