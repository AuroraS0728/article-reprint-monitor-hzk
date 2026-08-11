from django.contrib import admin
from django.http import HttpRequest

from .models import SearchRun, Source, SourceIngestToken


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "base_url", "is_active", "updated_at")
    search_fields = ("code", "name")


@admin.register(SourceIngestToken)
class SourceIngestTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "token_prefix", "created_by", "is_active", "expires_at", "last_used_at")
    fields = ("source", "name", "token_prefix", "created_by", "is_active", "expires_at", "last_used_at", "created_at")
    readonly_fields = ("token_prefix", "created_at", "last_used_at")
    search_fields = ("name", "source__code", "token_prefix", "created_by__username")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(SearchRun)
class SearchRunAdmin(admin.ModelAdmin):
    list_display = ("article", "provider", "status", "candidate_count", "matched_count", "created_at")
    readonly_fields = ("created_at",)
