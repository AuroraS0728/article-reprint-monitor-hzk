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


class ArticleIngestConflictStatus(models.TextChoices):
    PENDING = "PENDING", "待人工确认"
    APPROVED_AS_NEW = "APPROVED_AS_NEW", "批准为独立文章"
    LINKED_TO_EXISTING = "LINKED_TO_EXISTING", "关联到已有文章"
    REJECTED = "REJECTED", "已拒绝"


class ArticleIngestConflict(models.Model):
    source = models.ForeignKey(Source, related_name="article_ingest_conflicts", on_delete=models.PROTECT)
    existing_article = models.ForeignKey("articles.Article", related_name="source_conflicts", on_delete=models.PROTECT)
    created_article = models.ForeignKey(
        "articles.Article",
        related_name="approved_source_conflicts",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    linked_article = models.ForeignKey(
        "articles.Article",
        related_name="linked_source_conflicts",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    title = models.CharField(max_length=500)
    normalized_title = models.CharField(max_length=500, db_index=True)
    author = models.CharField(max_length=255)
    published_at = models.DateTimeField()
    published_date = models.DateField(db_index=True)
    original_url = models.URLField(max_length=2048)
    canonical_original_url = models.URLField(max_length=2048)
    source_item_key = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32,
        choices=ArticleIngestConflictStatus.choices,
        default=ArticleIngestConflictStatus.PENDING,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_article_ingest_conflicts", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reviewed_article_ingest_conflicts",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "sources_article_ingest_conflict"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "source_item_key"], name="uniq_source_ingest_conflict_item")
        ]


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
