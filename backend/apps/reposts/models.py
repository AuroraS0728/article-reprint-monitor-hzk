from django.conf import settings
from django.db import models


class RepostRecord(models.Model):
    article = models.ForeignKey("articles.Article", related_name="repost_records", on_delete=models.PROTECT)
    platform = models.ForeignKey("platforms.Platform", related_name="repost_records", on_delete=models.PROTECT)
    original_url = models.URLField(max_length=2048)
    normalized_url = models.URLField(max_length=2048)
    normalized_url_hash = models.CharField(max_length=64)
    final_url = models.URLField(max_length=2048, blank=True)
    repost_title = models.CharField(max_length=500)
    repost_published_at = models.DateTimeField(null=True, blank=True)
    first_discovered_at = models.DateTimeField()
    last_checked_at = models.DateTimeField()
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
            models.UniqueConstraint(fields=["article", "platform", "normalized_url_hash"], name="uniq_repost_url")
        ]
        ordering = ["repost_published_at", "first_discovered_at", "id"]

    @property
    def is_manual_supplement(self) -> bool:
        return self.data_source == "MANUAL_SUPPLEMENT"
