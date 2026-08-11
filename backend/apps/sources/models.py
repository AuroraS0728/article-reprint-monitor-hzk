from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

source_code_validator = RegexValidator(
    regex=r"^[A-Z0-9_]+$",
    message="来源代码只能包含大写英文字母、数字和下划线。",
)


class Source(models.Model):
    code = models.CharField(max_length=50, unique=True, validators=[source_code_validator])
    name = models.CharField(max_length=100)
    base_url = models.URLField(max_length=2048)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sources_source"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class SourceIngestToken(models.Model):
    source = models.ForeignKey(Source, related_name="ingest_tokens", on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    token_prefix = models.CharField(max_length=16, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sources_ingest_token"
        ordering = ["-created_at", "-id"]


class SearchRunStatus(models.TextChoices):
    PENDING = "PENDING", "待执行"
    RUNNING = "RUNNING", "执行中"
    SUCCESS = "SUCCESS", "成功"
    ERROR = "ERROR", "失败"


class SearchRun(models.Model):
    article = models.ForeignKey("articles.Article", related_name="search_runs", on_delete=models.CASCADE)
    provider = models.CharField(max_length=50)
    query = models.TextField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=SearchRunStatus.choices, default=SearchRunStatus.PENDING)
    candidate_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    new_repost_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sources_search_run"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["article", "status", "created_at"])]
