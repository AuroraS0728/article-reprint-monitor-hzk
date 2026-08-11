from __future__ import annotations

from rest_framework import serializers

from apps.articles.models import Article
from apps.platforms.models import Platform

from .models import RepostRecord


class ManualRepostCreateSerializer(serializers.Serializer[object]):
    article = serializers.PrimaryKeyRelatedField(queryset=Article.objects.all())
    platform = serializers.PrimaryKeyRelatedField(queryset=Platform.objects.all())
    repost_url = serializers.URLField(max_length=2048)
    reason = serializers.CharField(max_length=500, trim_whitespace=True)

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("人工补录原因不能为空。")
        return value.strip()


class ManualRepostStateSerializer(serializers.Serializer[object]):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)


class RepostRecordSerializer(serializers.ModelSerializer[RepostRecord]):
    article_title = serializers.CharField(source="article.title", read_only=True)
    platform_name = serializers.CharField(source="platform.name", read_only=True, default=None)
    manually_added_by_username = serializers.CharField(
        source="manually_added_by.username", read_only=True, default=None
    )
    invalidated_by_username = serializers.CharField(source="invalidated_by.username", read_only=True, default=None)

    class Meta:
        model = RepostRecord
        fields = [
            "id",
            "article",
            "article_title",
            "platform",
            "platform_name",
            "site_name",
            "site_domain",
            "raw_url",
            "canonical_url",
            "canonical_url_hash",
            "original_url",
            "normalized_url",
            "final_url",
            "repost_title",
            "result_title",
            "normalized_result_title",
            "similarity_score",
            "search_provider",
            "repost_published_at",
            "result_published_at",
            "first_discovered_at",
            "first_found_at",
            "last_checked_at",
            "last_seen_at",
            "availability_status",
            "last_availability_checked_at",
            "data_source",
            "manual_reason",
            "manually_added_by",
            "manually_added_by_username",
            "manually_added_at",
            "is_valid",
            "invalidated_by",
            "invalidated_by_username",
            "invalidated_at",
            "invalidation_reason",
        ]
        read_only_fields = fields
