from uuid import uuid4

from django.conf import settings
from django.db import models


def private_import_upload_path(instance: "ArticleImportJob", filename: str) -> str:
    return f"article-imports/{uuid4().hex}.xlsx"


class ArticleStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "监测中"
    STOPPED = "STOPPED", "停止监测"
    ARCHIVED = "ARCHIVED", "已归档"


class ImportStatus(models.TextChoices):
    PREVIEW = "PREVIEW", "待确认"
    COMPLETED = "COMPLETED", "已完成"


class ArticleMonitoringStatus(models.TextChoices):
    PENDING = "PENDING", "待监测"
    ACTIVE = "ACTIVE", "监测中"
    COMPLETED = "COMPLETED", "已完成"
    ERROR = "ERROR", "异常"


class ArticleIngestMethod(models.TextChoices):
    MANUAL = "MANUAL", "手工录入"
    EXCEL = "EXCEL", "Excel 导入"
    BULK_PASTE = "BULK_PASTE", "批量粘贴"
    SOURCE_API = "SOURCE_API", "来源接口"


class Article(models.Model):
    source = models.ForeignKey(
        "sources.Source", related_name="articles", null=True, blank=True, on_delete=models.PROTECT
    )
    source_item_key = models.CharField(max_length=128, null=True, blank=True)
    title = models.CharField(max_length=500)
    normalized_title = models.CharField(max_length=500, db_index=True)
    published_date = models.DateField(db_index=True)
    author = models.CharField(max_length=255, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    original_url = models.URLField(max_length=2048, blank=True)
    source_platform = models.CharField(max_length=100, blank=True)
    author_department = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=ArticleStatus.choices, default=ArticleStatus.ACTIVE, db_index=True)
    discovered_at = models.DateTimeField(null=True, blank=True)
    monitor_started_at = models.DateTimeField(null=True, blank=True)
    monitor_until = models.DateTimeField(null=True, blank=True, db_index=True)
    retention_until = models.DateTimeField(null=True, blank=True, db_index=True)
    last_searched_at = models.DateTimeField(null=True, blank=True)
    next_search_at = models.DateTimeField(null=True, blank=True, db_index=True)
    monitoring_status = models.CharField(
        max_length=16,
        choices=ArticleMonitoringStatus.choices,
        default=ArticleMonitoringStatus.PENDING,
        db_index=True,
    )
    ingest_method = models.CharField(
        max_length=16,
        choices=ArticleIngestMethod.choices,
        default=ArticleIngestMethod.MANUAL,
        db_index=True,
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_article"
        constraints = [
            models.UniqueConstraint(fields=["source", "source_item_key"], name="uniq_source_article_item"),
        ]
        ordering = ["-published_date", "-id"]


class ArticleImportJob(models.Model):
    original_filename = models.CharField(max_length=255)
    uploaded_file = models.FileField(upload_to=private_import_upload_path, max_length=300, blank=True)
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=ImportStatus.choices, default=ImportStatus.PREVIEW)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    preview_rows = models.JSONField(default=list)
    imported_article_ids = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "article_import_job"
        ordering = ["-created_at"]
