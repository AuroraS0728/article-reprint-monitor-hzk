from datetime import date
from typing import cast

from rest_framework import serializers

from .models import Article, ArticleImportJob
from .services import normalize_title


class ArticleSerializer(serializers.ModelSerializer[Article]):
    class Meta:
        model = Article
        fields = [
            "id",
            "title",
            "normalized_title",
            "published_date",
            "original_url",
            "source_platform",
            "author_department",
            "notes",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["normalized_title", "created_by", "created_at", "updated_at"]

    def validate_title(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("原创文章标题不能为空。")
        return value.strip()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        title = str(attrs.get("title", getattr(self.instance, "title", "")))
        published_date = attrs.get("published_date", getattr(self.instance, "published_date", None))
        if title and isinstance(published_date, date):
            duplicate = Article.objects.filter(normalized_title=normalize_title(title), published_date=published_date)
            if self.instance:
                duplicate = duplicate.exclude(pk=cast(Article, self.instance).pk)
            if duplicate.exists():
                raise serializers.ValidationError({"title": "同日存在相同标准化标题，请使用导入确认流程处理重复项。"})
        return attrs

    def create(self, validated_data: dict[str, object]) -> Article:
        validated_data["normalized_title"] = normalize_title(str(validated_data["title"]))
        return super().create(validated_data)

    def update(self, instance: Article, validated_data: dict[str, object]) -> Article:
        if "title" in validated_data:
            validated_data["normalized_title"] = normalize_title(str(validated_data["title"]))
        return super().update(instance, validated_data)


class ArticleImportJobSerializer(serializers.ModelSerializer[ArticleImportJob]):
    class Meta:
        model = ArticleImportJob
        fields = [
            "id",
            "original_filename",
            "sha256",
            "status",
            "total_rows",
            "valid_rows",
            "duplicate_rows",
            "failed_rows",
            "preview_rows",
            "imported_article_ids",
            "created_at",
            "completed_at",
        ]
