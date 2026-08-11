from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.articles.models import Article
from apps.core.redaction import safe_error_message
from apps.monitoring.models import DetectionBatch, DetectionResult, StatusSnapshot, TaskFailureLog
from apps.reports.models import GeneratedReport, ReportEmailDelivery
from apps.reposts.models import RepostRecord
from apps.sources.services import purge_expired_source_articles

from .models import DatabaseBackup, MaintenanceRun, MaintenanceStatus, SystemRuntimeConfiguration

ARTICLE_RETENTION_DAYS = 365
REPOST_RETENTION_DAYS = 365
STATISTICS_RETENTION_DAYS = 365
TASK_LOG_RETENTION_DAYS = 30
EMAIL_LOG_RETENTION_DAYS = 30
REPORT_FILE_RETENTION_DAYS = 30
BACKUP_RETENTION_DAYS = 30


def runtime_configuration() -> SystemRuntimeConfiguration:
    config, _ = SystemRuntimeConfiguration.objects.get_or_create(pk=1)
    return config


def _safe_delete_field_file(field_file: Any) -> bool:
    name = str(getattr(field_file, "name", ""))
    if not name or name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
        return False
    field_file.delete(save=False)
    return True


def cleanup_expired_data() -> MaintenanceRun:
    config = runtime_configuration()
    run = MaintenanceRun.objects.create(operation_name="cleanup_expired_data")
    if not config.maintenance_enabled:
        run.status = MaintenanceStatus.SKIPPED
        run.details = {"reason": "maintenance_disabled"}
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "details", "completed_at"])
        return run

    now = timezone.now()
    details: dict[str, int] = {}
    try:
        for report in GeneratedReport.objects.filter(
            generated_at__lt=now - timedelta(days=REPORT_FILE_RETENTION_DAYS)
        ).exclude(report_file=""):
            if _safe_delete_field_file(report.report_file):
                report.report_file = ""
                report.save(update_fields=["report_file"])
                details["report_files_deleted"] = details.get("report_files_deleted", 0) + 1

        for backup in DatabaseBackup.objects.filter(created_at__lt=now - timedelta(days=BACKUP_RETENTION_DAYS)):
            _safe_delete_field_file(backup.backup_file)
            backup.delete()
            details["backup_records_deleted"] = details.get("backup_records_deleted", 0) + 1

        task_deleted, _ = TaskFailureLog.objects.filter(
            created_at__lt=now - timedelta(days=TASK_LOG_RETENTION_DAYS)
        ).delete()
        details["task_logs_deleted"] = task_deleted
        email_deleted, _ = ReportEmailDelivery.objects.filter(
            created_at__lt=now - timedelta(days=EMAIL_LOG_RETENTION_DAYS)
        ).delete()
        details["email_logs_deleted"] = email_deleted

        # Global-search reposts are sticky historical facts. They are removed only
        # together with their Article after that Article reaches retention_until.
        global_purge = purge_expired_source_articles()
        details.update({f"global_{key}": value for key, value in global_purge.items()})

        expiring_reports = GeneratedReport.objects.filter(
            generated_at__lt=now - timedelta(days=STATISTICS_RETENTION_DAYS), email_deliveries__isnull=True
        )
        report_deleted, _ = expiring_reports.delete()
        details["report_records_deleted"] = report_deleted
        retained_snapshot_ids = GeneratedReport.objects.values_list("snapshot_id", flat=True)
        snapshot_deleted, _ = (
            StatusSnapshot.objects.filter(created_at__lt=now - timedelta(days=STATISTICS_RETENTION_DAYS))
            .exclude(id__in=retained_snapshot_ids)
            .delete()
        )
        details["statistics_snapshots_deleted"] = snapshot_deleted
        retained_batch_ids = StatusSnapshot.objects.exclude(source_batch_id=None).values_list(
            "source_batch_id", flat=True
        )
        batch_deleted, _ = (
            DetectionBatch.objects.filter(created_at__lt=now - timedelta(days=STATISTICS_RETENTION_DAYS))
            .exclude(id__in=retained_batch_ids)
            .delete()
        )
        details["detection_batches_deleted"] = batch_deleted

        protected_article_ids = set(DetectionResult.objects.values_list("article_id", flat=True))
        articles = Article.objects.filter(
            retention_until__isnull=True,
            published_date__lt=(now - timedelta(days=ARTICLE_RETENTION_DAYS)).date(),
        )
        safe_articles = articles.exclude(id__in=protected_article_ids)
        legacy_repost_deleted, _ = RepostRecord.objects.filter(article_id__in=safe_articles).delete()
        details["legacy_repost_records_deleted"] = legacy_repost_deleted
        article_deleted, _ = safe_articles.delete()
        details["articles_deleted"] = article_deleted
        details["articles_retained_for_referential_integrity"] = articles.count()

        run.status = MaintenanceStatus.SUCCEEDED
        run.details = details
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "details", "completed_at"])
    except Exception as error:
        run.status = MaintenanceStatus.FAILED
        run.error_message = safe_error_message(error)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_message", "completed_at"])
        raise
    return run


def create_database_backup() -> DatabaseBackup:
    config = runtime_configuration()
    backup = DatabaseBackup.objects.create()
    if not config.database_backup_enabled:
        backup.status = MaintenanceStatus.SKIPPED
        backup.error_message = "database_backup_disabled"
        backup.completed_at = timezone.now()
        backup.save(update_fields=["status", "error_message", "completed_at"])
        return backup
    database = settings.DATABASES["default"]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = str(database["PASSWORD"])
    command = [
        "mysqldump",
        "--single-transaction",
        "--skip-lock-tables",
        f"--host={database['HOST']}",
        f"--port={database['PORT']}",
        f"--user={database['USER']}",
        str(database["NAME"]),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=300,
            env=environment,
        )
        content = result.stdout
        if not content:
            raise RuntimeError("mysqldump returned no data")
        backup.backup_file.save("database.sql", ContentFile(content), save=False)
        backup.file_sha256 = hashlib.sha256(content).hexdigest()
        backup.size_bytes = len(content)
        backup.status = MaintenanceStatus.SUCCEEDED
        backup.completed_at = timezone.now()
        backup.save(update_fields=["backup_file", "file_sha256", "size_bytes", "status", "completed_at"])
    except Exception as error:
        backup.status = MaintenanceStatus.FAILED
        backup.error_message = safe_error_message(error)
        backup.completed_at = timezone.now()
        backup.save(update_fields=["status", "error_message", "completed_at"])
    return backup
