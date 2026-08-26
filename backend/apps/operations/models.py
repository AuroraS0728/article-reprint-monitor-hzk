from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models


def database_backup_path(instance: DatabaseBackup, filename: str) -> str:
    return f"database-backups/{uuid4().hex}.sql"


class MaintenanceStatus(models.TextChoices):
    RUNNING = "RUNNING", "运行中"
    SUCCEEDED = "SUCCEEDED", "成功"
    FAILED = "FAILED", "失败"
    SKIPPED = "SKIPPED", "跳过"


class SystemRuntimeConfiguration(models.Model):
    maintenance_enabled = models.BooleanField(default=True)
    database_backup_enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_system_runtime_configuration"


class MaintenanceRun(models.Model):
    operation_name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=16,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.RUNNING,
    )
    details = models.JSONField(default=dict)
    error_message = models.CharField(max_length=1000, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "operations_maintenance_run"
        ordering = ["-started_at", "-id"]


class DatabaseBackup(models.Model):
    status = models.CharField(
        max_length=16,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.RUNNING,
    )
    backup_file = models.FileField(
        upload_to=database_backup_path, max_length=300, blank=True
    )
    file_sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    error_message = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "operations_database_backup"
        ordering = ["-created_at", "-id"]
