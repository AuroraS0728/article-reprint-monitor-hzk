from __future__ import annotations

from rest_framework import serializers

from search_providers.exceptions import SearchProviderError

from .models import (
    ArticleIngestConflict,
    ArticleIngestConflictStatus,
    ReadingMetricStatus,
    SearchProviderConfiguration,
    SearchRunCandidate,
)


class SearchProviderConfigurationSerializer(serializers.ModelSerializer[SearchProviderConfiguration]):
    class Meta:
        model = SearchProviderConfiguration
        fields = [
            "id",
            "code",
            "name",
            "enabled",
            "priority",
            "last_success_at",
            "last_failure_at",
            "consecutive_failures",
            "last_failure_code",
            "last_failure_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "last_success_at",
            "last_failure_at",
            "consecutive_failures",
            "last_failure_code",
            "last_failure_message",
            "created_at",
            "updated_at",
        ]

    def validate_code(self, value: str) -> str:
        from search_providers.registry import SUPPORTED_PROVIDER_CODES

        code = value.strip().lower()
        if code not in SUPPORTED_PROVIDER_CODES:
            raise serializers.ValidationError("仅允许已实现且可审计的正式搜索来源。")
        return code

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        from search_providers.registry import search_provider_for_code

        enabled = bool(attrs.get("enabled", getattr(self.instance, "enabled", False)))
        code = str(attrs.get("code", getattr(self.instance, "code", "")))
        if enabled:
            try:
                search_provider_for_code(code)
            except SearchProviderError as error:
                raise serializers.ValidationError(
                    {"enabled": "来源密钥未在服务器安全配置中就绪，不能启用。"}
                ) from error
        return attrs


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
            "provider_codes",
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


class SearchRunCandidateReviewSerializer(serializers.Serializer[object]):
    """Human classification is explicit: no candidate is silently discarded."""

    action = serializers.ChoiceField(
        choices=["CONFIRM_REPOST", "CONFIRM_OWNED", "EXCLUDE"],
    )
    reason = serializers.CharField(max_length=450, trim_whitespace=True, allow_blank=False)
    owned_channel_id = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs["action"] == "CONFIRM_OWNED" and not attrs.get("owned_channel_id"):
            raise serializers.ValidationError({"owned_channel_id": "归入阅读量时必须选择自有渠道。"})
        if attrs["action"] != "CONFIRM_OWNED" and attrs.get("owned_channel_id"):
            raise serializers.ValidationError({"owned_channel_id": "仅归入阅读量时可以指定自有渠道。"})
        return attrs


class TargetedCrawlCandidateItemSerializer(serializers.Serializer[object]):
    """Untrusted browser result data; the server derives the canonical host and URL."""

    title = serializers.CharField(max_length=500, trim_whitespace=True)
    url = serializers.URLField(max_length=2048)
    site_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    published_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    search_phase = serializers.ChoiceField(choices=["EXACT", "BROAD"], required=False, default="EXACT")
    provider_code = serializers.RegexField(
        regex=r"^[a-z0-9_]{1,50}$",
        required=False,
        default="targeted_crawl",
    )

    def validate_title(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("候选标题不能为空。")
        return value.strip()


class TargetedCrawlCandidatesSerializer(serializers.Serializer[object]):
    task_id = serializers.IntegerField(min_value=1)
    run_id = serializers.IntegerField(min_value=1)
    claim_token = serializers.CharField(min_length=32, max_length=256, trim_whitespace=True, write_only=True)
    candidates = TargetedCrawlCandidateItemSerializer(many=True)

    def validate_candidates(self, value: object) -> object:
        if not isinstance(value, list) or not 1 <= len(value) <= 100:
            raise serializers.ValidationError("每次最多提交 100 条候选结果，且至少需要 1 条。")
        return value


class TargetedCrawlRunSerializer(serializers.Serializer[object]):
    task_id = serializers.IntegerField(min_value=1)
    run_id = serializers.IntegerField(min_value=1)
    claim_token = serializers.CharField(min_length=32, max_length=256, trim_whitespace=True, write_only=True)
    status = serializers.ChoiceField(choices=["SUCCESS", "PARTIAL_SUCCESS", "ERROR"])
    error_code = serializers.RegexField(
        regex=r"^[A-Z0-9_]{1,64}$",
        required=False,
        allow_blank=True,
        default="",
    )
    error_message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs["status"] == "ERROR" and not attrs.get("error_code"):
            raise serializers.ValidationError({"error_code": "失败运行必须提供错误代码。"})
        if attrs["status"] in {"SUCCESS", "PARTIAL_SUCCESS"} and (
            attrs.get("error_code") or attrs.get("error_message")
        ):
            raise serializers.ValidationError("成功运行不能携带失败详情。")
        return attrs


class ReadingMetricObservationItemSerializer(serializers.Serializer[object]):
    publication_id = serializers.IntegerField(min_value=1)
    reading_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    observed_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(
        choices=ReadingMetricStatus.values,
        required=False,
        default=ReadingMetricStatus.SUCCESS,
    )
    error_message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if (
            attrs.get("status", ReadingMetricStatus.SUCCESS) == ReadingMetricStatus.SUCCESS
            and attrs.get("reading_count") is None
        ):
            raise serializers.ValidationError({"reading_count": "成功获取阅读量时必须提供 reading_count。"})
        return attrs


class ReadingMetricObservationSubmitSerializer(serializers.Serializer[object]):
    observations = ReadingMetricObservationItemSerializer(many=True)

    def validate_observations(self, value: object) -> object:
        if not isinstance(value, list) or not 1 <= len(value) <= 100:
            raise serializers.ValidationError("每次最多提交 100 条阅读量观测，且至少需要 1 条。")
        return value


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
