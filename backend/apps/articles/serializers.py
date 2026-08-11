from datetime import date
from typing import cast

from rest_framework import serializers

from .models import Article, ArticleImportJob
from .services import normalize_title


class ArticleSerializer(serializers.ModelSerializer[Article]):
    repost_site_count = serializers.SerializerMethodField()
    repost_url_count = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id",
            "title",
            "normalized_title",
            "source",
            "source_item_key",
            "published_date",
            "published_at",
            "author",
            "original_url",
            "source_platform",
            "author_department",
            "notes",
            "status",
            "monitoring_status",
            "monitor_started_at",
            "monitor_until",
            "retention_until",
            "last_searched_at",
            "next_search_at",
            "ingest_method",
            "repost_site_count",
            "repost_url_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "normalized_title",
            "source",
            "source_item_key",
            "monitoring_status",
            "monitor_started_at",
            "monitor_until",
            "retention_until",
            "last_searched_at",
            "next_search_at",
            "ingest_method",
            "repost_site_count",
            "repost_url_count",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_repost_site_count(self, instance: Article) -> int:
        domains = {
            record.site_domain or (record.platform.name if record.platform is not None else "")
            for record in instance.repost_records.filter(is_valid=True).select_related("platform")
        }
        return len(domains - {""})

    def get_repost_url_count(self, instance: Article) -> int:
        return instance.repost_records.filter(is_valid=True).count()

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
