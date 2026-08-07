from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models


def report_upload_path(instance: GeneratedReport, filename: str) -> str:
    return f"generated-reports/{instance.report_type.lower()}/{uuid4().hex}.xlsx"


class ReportType(models.TextChoices):
    DAILY = "DAILY", "日报"
    WEEKLY = "WEEKLY", "周报"


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "待发送"
    SENT = "SENT", "已发送"
    FAILED = "FAILED", "发送失败"


class GeneratedReport(models.Model):
    report_type = models.CharField(max_length=16, choices=ReportType.choices)
    report_date = models.DateField(db_index=True, help_text="日报日期或周报周一日期")
    version = models.PositiveSmallIntegerField(default=1)
    period_start = models.DateField()
    period_end = models.DateField()
    snapshot = models.ForeignKey("monitoring.StatusSnapshot", on_delete=models.PROTECT)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    generated_at = models.DateTimeField(auto_now_add=True)
    report_file = models.FileField(upload_to=report_upload_path, max_length=300)
    file_sha256 = models.CharField(max_length=64)
    statistics_range = models.JSONField(default=dict)

    class Meta:
        db_table = "reports_generated_report"
        constraints = [
            models.UniqueConstraint(fields=["report_type", "report_date", "version"], name="uniq_report_version")
        ]
        ordering = ["-report_date", "-version", "-id"]


class SMTPConfiguration(models.Model):
    host = models.CharField(max_length=253, blank=True)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=320, blank=True)
    from_email = models.EmailField(blank=True)
    encrypted_authorization_code = models.TextField(blank=True)
    recipients = models.JSONField(default=list)
    cc_recipients = models.JSONField(default=list)
    use_tls = models.BooleanField(default=True)
    enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports_smtp_configuration"


class ReportEmailDelivery(models.Model):
    report = models.ForeignKey(GeneratedReport, related_name="email_deliveries", on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    recipients = models.JSONField(default=list)
    cc_recipients = models.JSONField(default=list)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.CharField(max_length=1000, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reports_email_delivery"
        ordering = ["-created_at", "-id"]
