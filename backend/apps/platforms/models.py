from django.db import models


class PlatformStatus(models.TextChoices):
    PENDING = "PENDING", "待配置"
    TESTING = "TESTING", "测试中"
    ENABLED = "ENABLED", "已启用"
    DISABLED = "DISABLED", "已停用"
    BROKEN = "BROKEN", "规则失效"
    ARCHIVED = "ARCHIVED", "已归档"


class AdapterType(models.TextChoices):
    PUBLIC_API = "PUBLIC_API", "公开接口"
    HTML_SEARCH = "HTML_SEARCH", "HTML 搜索"
    PLAYWRIGHT = "PLAYWRIGHT", "浏览器采集"
    CHANNEL_SCAN = "CHANNEL_SCAN", "栏目扫描"
    RSS = "RSS", "RSS"
    SITEMAP = "SITEMAP", "Sitemap"
    CUSTOM = "CUSTOM", "专用适配器"


class Platform(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=16, choices=PlatformStatus.choices, default=PlatformStatus.PENDING
    )
    adapter_type = models.CharField(
        max_length=30, choices=AdapterType.choices, default=AdapterType.HTML_SEARCH
    )
    default_max_pages = models.PositiveSmallIntegerField(default=5)
    default_max_results = models.PositiveSmallIntegerField(default=100)
    request_interval_ms = models.PositiveIntegerField(default=2000)
    timeout_seconds = models.PositiveSmallIntegerField(default=15)
    retry_count = models.PositiveSmallIntegerField(default=2)
    confirmed_title_suffixes = models.JSONField(default=list, blank=True)
    config_version = models.PositiveIntegerField(default=1)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    consecutive_failure_count = models.PositiveIntegerField(default=0)
    last_failure_reason = models.CharField(max_length=500, blank=True)
    adapter_notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_platform"
        ordering = ["name"]


class PlatformDomain(models.Model):
    platform = models.ForeignKey(
        Platform, related_name="domains", on_delete=models.CASCADE
    )
    domain = models.CharField(max_length=253, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_domain"
