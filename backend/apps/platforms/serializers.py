import ipaddress
import re
from typing import cast

from rest_framework import serializers

from .models import Platform, PlatformDomain


class PlatformSerializer(serializers.ModelSerializer[Platform]):
    domain_names = serializers.ListField(child=serializers.CharField(max_length=253), write_only=True, required=False)
    domains: serializers.SlugRelatedField = serializers.SlugRelatedField(many=True, read_only=True, slug_field="domain")

    class Meta:
        model = Platform
        fields = [
            "id",
            "code",
            "name",
            "status",
            "adapter_type",
            "default_max_pages",
            "default_max_results",
            "request_interval_ms",
            "timeout_seconds",
            "retry_count",
            "confirmed_title_suffixes",
            "config_version",
            "last_verified_at",
            "adapter_notes",
            "domains",
            "domain_names",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "config_version", "last_verified_at", "created_at", "updated_at"]

    def validate_confirmed_title_suffixes(self, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise serializers.ValidationError("可确认标题后缀不能重复。")
        if any(len(value) > 100 for value in cleaned):
            raise serializers.ValidationError("单个可确认标题后缀不能超过 100 个字符。")
        return cleaned

    def validate_code(self, value: str) -> str:
        if not re.fullmatch(r"[A-Z0-9_]{2,50}", value):
            raise serializers.ValidationError("平台代码必须为2至50位大写字母、数字或下划线。")
        return value

    def validate_domain_names(self, values: list[str]) -> list[str]:
        clean: list[str] = []
        for value in values:
            domain = value.strip().lower().rstrip(".")
            if "://" in domain or "/" in domain or domain == "localhost":
                raise serializers.ValidationError("域名白名单只能使用公开域名，不接受协议、路径或 localhost。")
            try:
                ipaddress.ip_address(domain)
            except ValueError as error:
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", domain):
                    raise serializers.ValidationError("域名格式无效。") from error
            else:
                raise serializers.ValidationError("域名白名单不接受 IP 地址。")
            clean.append(domain)
        return list(dict.fromkeys(clean))

    def _replace_domains(self, platform: Platform, domains: list[str] | None) -> None:
        if domains is None:
            return
        platform.domains.all().delete()
        PlatformDomain.objects.bulk_create([PlatformDomain(platform=platform, domain=domain) for domain in domains])

    def create(self, validated_data: dict[str, object]) -> Platform:
        domains = cast(list[str], validated_data.pop("domain_names", []))
        platform = super().create(validated_data)
        self._replace_domains(platform, domains)
        return platform

    def update(self, instance: Platform, validated_data: dict[str, object]) -> Platform:
        domains = cast(list[str] | None, validated_data.pop("domain_names", None))
        platform = super().update(instance, validated_data)
        self._replace_domains(platform, domains)
        platform.config_version += 1
        platform.save(update_fields=["config_version", "updated_at"])
        return platform
