from django.contrib import admin
from django.http import HttpRequest

from .models import (
    ArticleIngestConflict,
    AutomaticRepostSite,
    OwnedChannel,
    ReadingMetricObservation,
    SearchProviderConfiguration,
    SearchRun,
    Source,
    SourceIngestToken,
)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "base_url", "is_active", "updated_at")
    search_fields = ("code", "name")


@admin.register(SourceIngestToken)
class SourceIngestTokenAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source",
        "token_prefix",
        "created_by",
        "is_active",
        "expires_at",
        "last_used_at",
    )
    fields = (
        "source",
        "name",
        "token_prefix",
        "created_by",
        "is_active",
        "expires_at",
        "last_used_at",
        "created_at",
    )
    readonly_fields = ("token_prefix", "created_at", "last_used_at")
    search_fields = ("name", "source__code", "token_prefix", "created_by__username")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(SearchRun)
class SearchRunAdmin(admin.ModelAdmin):
    list_display = (
        "article",
        "provider",
        "status",
        "candidate_count",
        "matched_count",
        "created_at",
    )
    readonly_fields = ("created_at",)


@admin.register(SearchProviderConfiguration)
class SearchProviderConfigurationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "enabled", "priority", "last_success_at", "consecutive_failures")
    list_filter = ("enabled",)
    search_fields = ("code", "name")
    readonly_fields = (
        "last_success_at",
        "last_failure_at",
        "consecutive_failures",
        "last_failure_code",
        "last_failure_message",
        "created_at",
        "updated_at",
    )


@admin.register(OwnedChannel)
class OwnedChannelAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "channel_type", "is_active", "updated_at")
    list_filter = ("channel_type", "is_active")
    search_fields = ("code", "name", "notes")


@admin.register(AutomaticRepostSite)
class AutomaticRepostSiteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "notes")


@admin.register(ReadingMetricObservation)
class ReadingMetricObservationAdmin(admin.ModelAdmin):
    list_display = ("repost_record", "source", "reading_count", "status", "observed_at", "created_at")
    list_filter = ("status", "source")
    search_fields = ("repost_record__article__title", "repost_record__canonical_url", "error_message")
    readonly_fields = ("created_at",)


@admin.register(ArticleIngestConflict)
class ArticleIngestConflictAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source",
        "existing_article",
        "status",
        "created_at",
        "reviewed_at",
    )
    list_filter = ("status", "source")
    search_fields = (
        "title",
        "normalized_title",
        "canonical_original_url",
        "source_item_key",
    )
    readonly_fields = ("created_at", "updated_at")
