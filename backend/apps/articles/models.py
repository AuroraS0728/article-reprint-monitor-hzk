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


class Article(models.Model):
    title = models.CharField(max_length=500)
    normalized_title = models.CharField(max_length=500, db_index=True)
    published_date = models.DateField(db_index=True)
    original_url = models.URLField(max_length=2048, blank=True)
    source_platform = models.CharField(max_length=100, blank=True)
    author_department = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=ArticleStatus.choices, default=ArticleStatus.ACTIVE, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_article"
        constraints = [
            models.UniqueConstraint(fields=["normalized_title", "published_date"], name="uniq_article_title_date")
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
