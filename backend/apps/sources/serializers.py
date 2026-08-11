from __future__ import annotations

from rest_framework import serializers


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
