from __future__ import annotations

from django.conf import settings
from django.db import models


class BatchTrigger(models.TextChoices):
    IMMEDIATE = "IMMEDIATE", "立即检测"
    AUTOMATIC = "AUTOMATIC", "自动检测"
    WEEKLY_FINAL = "WEEKLY_FINAL", "周最终检测"


class BatchStatus(models.TextChoices):
    PENDING = "PENDING", "待执行"
    RUNNING = "RUNNING", "执行中"
    COMPLETED = "COMPLETED", "已完成"
    FAILED = "FAILED", "失败"


class PlatformDetectionStatus(models.TextChoices):
    FOUND = "FOUND", "1"
    NOT_FOUND = "NOT_FOUND", "0"
    UNKNOWN = "UNKNOWN", "—"


class SnapshotType(models.TextChoices):
    DAILY = "DAILY", "日报状态"
    WEEKLY = "WEEKLY", "周报状态"


class DetectionBatch(models.Model):
    trigger = models.CharField(max_length=16, choices=BatchTrigger.choices)
    status = models.CharField(max_length=16, choices=BatchStatus.choices, default=BatchStatus.PENDING, db_index=True)
    article_ids = models.JSONField(default=list)
    platform_ids = models.JSONField(default=list)
    article_date_from = models.DateField(null=True, blank=True)
    article_date_to = models.DateField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, unique=True)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    failure_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monitoring_detection_batch"
        ordering = ["-created_at", "-id"]


class DetectionResult(models.Model):
    batch = models.ForeignKey(DetectionBatch, related_name="results", on_delete=models.CASCADE)
    article = models.ForeignKey("articles.Article", on_delete=models.PROTECT)
    platform = models.ForeignKey("platforms.Platform", on_delete=models.PROTECT)
    status = models.CharField(
        max_length=16, choices=PlatformDetectionStatus.choices, default=PlatformDetectionStatus.UNKNOWN
    )
    reason_code = models.CharField(max_length=64, blank=True)
    reason_message = models.CharField(max_length=500, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "monitoring_detection_result"
        constraints = [
            models.UniqueConstraint(fields=["batch", "article", "platform"], name="uniq_batch_article_platform")
        ]
        indexes = [models.Index(fields=["batch", "status"]), models.Index(fields=["article", "platform"])]


class StatusSnapshot(models.Model):
    snapshot_type = models.CharField(max_length=16, choices=SnapshotType.choices)
    cutoff_at = models.DateTimeField(db_index=True)
    source_batch = models.ForeignKey(DetectionBatch, null=True, blank=True, on_delete=models.PROTECT)
    matrix_data = models.JSONField(default=dict)
    statistics_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monitoring_status_snapshot"
        constraints = [models.UniqueConstraint(fields=["snapshot_type", "cutoff_at"], name="uniq_snapshot_type_cutoff")]


class TaskFailureLog(models.Model):
    task_name = models.CharField(max_length=200)
    batch = models.ForeignKey(DetectionBatch, null=True, blank=True, on_delete=models.SET_NULL)
    error_type = models.CharField(max_length=100)
    message = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monitoring_task_failure_log"
        ordering = ["-created_at"]
