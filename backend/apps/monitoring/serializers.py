from rest_framework import serializers

from .models import DetectionBatch, DetectionResult, StatusSnapshot


class DetectionBatchSerializer(serializers.ModelSerializer[DetectionBatch]):
    class Meta:
        model = DetectionBatch
        fields = [
            "id",
            "trigger",
            "status",
            "article_ids",
            "platform_ids",
            "article_date_from",
            "article_date_to",
            "scheduled_for",
            "started_at",
            "completed_at",
            "failure_message",
            "created_at",
        ]
        read_only_fields = [
            "status",
            "article_ids",
            "platform_ids",
            "scheduled_for",
            "started_at",
            "completed_at",
            "failure_message",
            "created_at",
        ]


class DetectionBatchCreateSerializer(serializers.Serializer[object]):
    article_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)
    platform_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)
    article_date_from = serializers.DateField(required=False)
    article_date_to = serializers.DateField(required=False)
    use_all_enabled_platforms = serializers.BooleanField(default=False)
    automatic = serializers.BooleanField(default=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if not attrs.get("article_ids") and not (attrs.get("article_date_from") or attrs.get("article_date_to")):
            raise serializers.ValidationError("请选择文章或原创发布日期范围。")
        if not attrs.get("platform_ids") and not attrs.get("use_all_enabled_platforms"):
            raise serializers.ValidationError("请选择平台或全部启用平台。")
        return attrs


class DetectionResultSerializer(serializers.ModelSerializer[DetectionResult]):
    article_title = serializers.CharField(source="article.title", read_only=True)
    platform_name = serializers.CharField(source="platform.name", read_only=True)

    class Meta:
        model = DetectionResult
        fields = [
            "id",
            "article",
            "article_title",
            "platform",
            "platform_name",
            "status",
            "reason_code",
            "reason_message",
            "attempt_count",
            "started_at",
            "completed_at",
        ]


class StatusSnapshotSerializer(serializers.ModelSerializer[StatusSnapshot]):
    class Meta:
        model = StatusSnapshot
        fields = ["id", "snapshot_type", "cutoff_at", "source_batch", "matrix_data", "statistics_data", "created_at"]
