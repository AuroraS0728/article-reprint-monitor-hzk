from __future__ import annotations

from rest_framework import serializers

from .models import (
    ArticleIngestConflict,
    ArticleIngestConflictStatus,
    SearchRunCandidate,
)


class SourceArticleIngestSerializer(serializers.Serializer[object]):
    title = serializers.CharField(max_length=500, trim_whitespace=True)
    author = serializers.CharField(max_length=255, trim_whitespace=True)
    published_at = serializers.DateTimeField()
    original_url = serializers.URLField(max_length=2048)
    channel_code = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    channel_name = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    section_code = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    section_name = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)

    def validate_title(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("标题不能为空。")
        return value.strip()

    def validate_author(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("作者不能为空。")
        return value.strip()


class ManualGlobalSearchSerializer(serializers.Serializer[object]):
    selection_mode = serializers.ChoiceField(choices=["IDS", "FILTER"], required=False, default="IDS")
    article_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=500,
        allow_empty=False,
        required=False,
    )
    filters = serializers.DictField(required=False)

    def validate_article_ids(self, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        mode = attrs.get("selection_mode", "IDS")
        if mode == "IDS" and not attrs.get("article_ids"):
            raise serializers.ValidationError({"article_ids": "请选择至少一篇文章。"})
        if mode == "FILTER" and not attrs.get("filters"):
            raise serializers.ValidationError({"filters": "按筛选范围检测需要筛选条件。"})
        return attrs


class SearchRunCandidateSerializer(serializers.ModelSerializer[SearchRunCandidate]):
    class Meta:
        model = SearchRunCandidate
        fields = [
            "id",
            "title",
            "site_name",
            "site_domain",
            "raw_url",
            "canonical_url",
            "published_at",
            "search_phases",
            "content_relation",
            "owned_channel",
            "classification_reason",
            "classified_at",
            "disposition",
            "similarity_score",
            "reason_code",
            "created_at",
        ]
        read_only_fields = fields


class ArticleIngestConflictSerializer(serializers.ModelSerializer[ArticleIngestConflict]):
    class Meta:
        model = ArticleIngestConflict
        fields = [
            "id",
            "source",
            "existing_article",
            "created_article",
            "linked_article",
            "title",
            "normalized_title",
            "author",
            "published_at",
            "published_date",
            "original_url",
            "canonical_original_url",
            "source_item_key",
            "status",
            "created_by",
            "created_at",
            "updated_at",
            "reviewed_by",
            "reviewed_at",
            "review_reason",
        ]
        read_only_fields = fields


class ArticleIngestConflictReviewSerializer(serializers.Serializer[object]):
    action = serializers.ChoiceField(
        choices=[
            ArticleIngestConflictStatus.APPROVED_AS_NEW,
            ArticleIngestConflictStatus.LINKED_TO_EXISTING,
        ]
    )
    reason = serializers.CharField(max_length=2000, trim_whitespace=True, allow_blank=False)
    article_id = serializers.IntegerField(required=False, min_value=1)
