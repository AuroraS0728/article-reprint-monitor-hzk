from __future__ import annotations

from rest_framework import serializers

from .models import ArticleIngestConflict, ArticleIngestConflictStatus


class SourceArticleIngestSerializer(serializers.Serializer[object]):
    title = serializers.CharField(max_length=500, trim_whitespace=True)
    author = serializers.CharField(max_length=255, trim_whitespace=True)
    published_at = serializers.DateTimeField()
    original_url = serializers.URLField(max_length=2048)

    def validate_title(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("标题不能为空。")
        return value.strip()

    def validate_author(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("作者不能为空。")
        return value.strip()


class ManualGlobalSearchSerializer(serializers.Serializer[object]):
    article_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=50,
        allow_empty=False,
    )

    def validate_article_ids(self, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


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
