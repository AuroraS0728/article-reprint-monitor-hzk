from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

source_code_validator = RegexValidator(
    regex=r"^[A-Z0-9_]+$",
    message="来源代码只能包含大写英文字母、数字和下划线。",
)
search_provider_code_validator = RegexValidator(
    regex=r"^[a-z0-9_]+$",
    message="搜索来源代码只能包含小写英文字母、数字和下划线。",
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


class OwnedChannelType(models.TextChoices):
    OFFICIAL_WEBSITE = "OFFICIAL_WEBSITE", "官方网站"
    PLATFORM_ACCOUNT = "PLATFORM_ACCOUNT", "平台账号"
    WECHAT_ACCOUNT = "WECHAT_ACCOUNT", "公众号"


class OwnedChannel(models.Model):
    """A configurable first-party distribution channel, never a scattered domain rule."""

    code = models.CharField(max_length=64, unique=True, validators=[source_code_validator])
    name = models.CharField(max_length=100, unique=True)
    channel_type = models.CharField(max_length=32, choices=OwnedChannelType.choices)
    is_active = models.BooleanField(default=True, db_index=True)
    match_rules = models.JSONField(default=dict)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sources_owned_channel"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class AutomaticRepostSite(models.Model):
    """Database-managed media-site rule for low-touch repost confirmation.

    This is deliberately separate from ``OwnedChannel``: the latter takes
    precedence when it positively identifies first-party distribution.  A site
    here may confirm an otherwise reviewable title match at the candidate
    threshold, but never supplies a browser adapter or a search credential.
    """

    code = models.CharField(max_length=64, unique=True, validators=[source_code_validator])
    name = models.CharField(max_length=100, unique=True)
    domains = models.JSONField(default=list)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sources_automatic_repost_site"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class SearchProviderConfiguration(models.Model):
    """Database-managed provider order. API credentials stay in server secrets."""

    code = models.CharField(max_length=50, unique=True, validators=[search_provider_code_validator])
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=False, db_index=True)
    priority = models.PositiveSmallIntegerField(default=100)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_failure_code = models.CharField(max_length=64, blank=True)
    last_failure_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sources_search_provider_configuration"
        ordering = ["priority", "code"]

    def __str__(self) -> str:
        return f"{self.priority} - {self.code}"


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
        settings.AUTH_USER_MODEL,
        related_name="created_article_ingest_conflicts",
        on_delete=models.PROTECT,
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
            models.UniqueConstraint(
                fields=["source", "source_item_key"],
                name="uniq_source_ingest_conflict_item",
            )
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
    exact_candidate_count = models.PositiveIntegerField(default=0)
    broad_candidate_count = models.PositiveIntegerField(default=0)
    merged_candidate_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    owned_count = models.PositiveIntegerField(default=0)
    repost_count = models.PositiveIntegerField(default=0)
    review_required_count = models.PositiveIntegerField(default=0)
    new_repost_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sources_search_run"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["article", "status", "created_at"])]


class SearchCandidateDisposition(models.TextChoices):
    PENDING = "PENDING", "待比对"
    EXCLUDED_SOURCE = "EXCLUDED_SOURCE", "原创来源链接"
    EXCLUDED_ORIGINAL = "EXCLUDED_ORIGINAL", "原创文章链接"
    EXCLUDED_TOO_EARLY = "EXCLUDED_TOO_EARLY", "发布时间早于原创"
    EXCLUDED_MANUAL = "EXCLUDED_MANUAL", "人工排除"
    NOT_MATCHED = "NOT_MATCHED", "未匹配"
    MATCHED = "MATCHED", "已匹配转载"


class SearchRunCandidate(models.Model):
    """A sanitized, inspectable candidate retained until its source article expires."""

    search_run = models.ForeignKey(SearchRun, related_name="candidates", on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    site_name = models.CharField(max_length=255, blank=True)
    site_domain = models.CharField(max_length=253, blank=True, db_index=True)
    raw_url = models.URLField(max_length=2048)
    canonical_url = models.URLField(max_length=2048)
    canonical_url_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True, blank=True)
    search_phases = models.JSONField(default=list)
    provider_codes = models.JSONField(default=list)
    content_relation = models.CharField(max_length=20, blank=True, default="", db_index=True)
    owned_channel = models.ForeignKey(
        OwnedChannel,
        related_name="search_candidates",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    classification_reason = models.CharField(max_length=500, blank=True, default="")
    classified_at = models.DateTimeField(null=True, blank=True)
    disposition = models.CharField(
        max_length=32,
        choices=SearchCandidateDisposition.choices,
        default=SearchCandidateDisposition.PENDING,
    )
    similarity_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sources_search_run_candidate"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["search_run", "canonical_url_hash"],
                name="uniq_search_run_candidate_url",
            )
        ]


class TargetedCrawlTaskStatus(models.TextChoices):
    """Lifecycle of a browser-worker task, distinct from an individual SearchRun."""

    PENDING = "PENDING", "待领取"
    CLAIMED = "CLAIMED", "已领取"
    CLOSED = "CLOSED", "已关闭"


class TargetedCrawlTask(models.Model):
    """A source-scoped, leased task for an approved local browser worker.

    The task stores no browser cookies, search-page HTML or account credentials.  A
    short-lived claim secret is returned once to the worker and only its hash is
    retained server-side.
    """

    source = models.ForeignKey(Source, related_name="targeted_crawl_tasks", on_delete=models.PROTECT)
    article = models.OneToOneField(
        "articles.Article",
        related_name="targeted_crawl_task",
        on_delete=models.CASCADE,
    )
    query = models.CharField(max_length=500)
    status = models.CharField(
        max_length=16,
        choices=TargetedCrawlTaskStatus.choices,
        default=TargetedCrawlTaskStatus.PENDING,
        db_index=True,
    )
    claimed_by_token = models.ForeignKey(
        "SourceIngestToken",
        related_name="claimed_targeted_crawl_tasks",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    claim_token_hash = models.CharField(max_length=64, blank=True, default="")
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    next_available_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_completed_at = models.DateTimeField(null=True, blank=True)
    last_run = models.ForeignKey(
        SearchRun,
        related_name="targeted_crawl_tasks",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_message = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sources_targeted_crawl_task"
        ordering = ["next_available_at", "id"]
        indexes = [
            models.Index(
                fields=["source", "status", "next_available_at"],
                name="sources_tar_source__cbb47e_idx",
            )
        ]
