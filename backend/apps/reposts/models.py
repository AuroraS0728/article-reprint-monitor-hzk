from django.conf import settings
from django.db import models


class ContentRelation(models.TextChoices):
    REPOST = "REPOST", "外部转载"
    OWNED = "OWNED", "自有分发"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "待审核"


class RepostRecord(models.Model):
    article = models.ForeignKey("articles.Article", related_name="repost_records", on_delete=models.PROTECT)
    platform = models.ForeignKey(
        "platforms.Platform",
        related_name="repost_records",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    site_name = models.CharField(max_length=255, blank=True)
    site_domain = models.CharField(max_length=253, blank=True, db_index=True)
    raw_url = models.URLField(max_length=2048, blank=True)
    canonical_url = models.URLField(max_length=2048, null=True, blank=True)
    canonical_url_hash = models.CharField(max_length=64, null=True, blank=True)
    original_url = models.URLField(max_length=2048)
    normalized_url = models.URLField(max_length=2048)
    normalized_url_hash = models.CharField(max_length=64)
    final_url = models.URLField(max_length=2048, blank=True)
    repost_title = models.CharField(max_length=500)
    result_title = models.CharField(max_length=500, blank=True)
    normalized_result_title = models.CharField(max_length=500, blank=True)
    similarity_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    search_provider = models.CharField(max_length=50, blank=True)
    content_relation = models.CharField(
        max_length=20,
        choices=ContentRelation.choices,
        default=ContentRelation.REPOST,
        db_index=True,
    )
    owned_channel = models.ForeignKey(
        "sources.OwnedChannel",
        related_name="discovered_records",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    classification_reason = models.CharField(max_length=500, blank=True, default="")
    classified_at = models.DateTimeField(null=True, blank=True)
    repost_published_at = models.DateTimeField(null=True, blank=True)
    result_published_at = models.DateTimeField(null=True, blank=True)
    first_discovered_at = models.DateTimeField()
    first_found_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)
    availability_status = models.CharField(
        max_length=16,
        choices=[
            ("UNKNOWN", "未知"),
            ("AVAILABLE", "正常"),
            ("UNAVAILABLE", "不可访问"),
            ("REMOVED", "已删除"),
        ],
        default="UNKNOWN",
        db_index=True,
    )
    last_availability_checked_at = models.DateTimeField(null=True, blank=True)
    data_source = models.CharField(max_length=100)
    manual_reason = models.CharField(max_length=500, blank=True)
    manually_added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="manual_repost_records",
        on_delete=models.SET_NULL,
    )
    manually_added_at = models.DateTimeField(null=True, blank=True)
    is_valid = models.BooleanField(default=True, db_index=True)
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="invalidated_manual_repost_records",
        on_delete=models.SET_NULL,
    )
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reposts_repost_record"
        constraints = [
            models.UniqueConstraint(
                fields=["article", "platform", "normalized_url_hash"],
                name="uniq_repost_url",
            ),
            models.UniqueConstraint(
                fields=["article", "canonical_url_hash"],
                name="uniq_article_canonical_hash",
            ),
        ]
        ordering = ["repost_published_at", "first_discovered_at", "id"]

    @property
    def is_manual_supplement(self) -> bool:
        return self.data_source == "MANUAL_SUPPLEMENT"

    @property
    def is_historical_repost(self) -> bool:
        """Existence is the repost fact; availability never revokes it."""

        return self.is_valid and self.content_relation == ContentRelation.REPOST
