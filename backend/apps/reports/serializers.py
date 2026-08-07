from __future__ import annotations

from rest_framework import serializers

from .mail_services import encrypt_authorization_code
from .models import GeneratedReport, ReportEmailDelivery, SMTPConfiguration


class ReportSerializer(serializers.ModelSerializer[GeneratedReport]):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedReport
        fields = [
            "id", "report_type", "report_date", "version", "period_start", "period_end", "generated_at",
            "generated_by", "statistics_range", "file_sha256", "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, instance: GeneratedReport) -> str:
        return f"/api/v1/reports/{instance.id}/download"


class SMTPConfigurationSerializer(serializers.ModelSerializer[SMTPConfiguration]):
    authorization_code = serializers.CharField(write_only=True, required=False, allow_blank=False)
    authorization_code_configured = serializers.BooleanField(source="encrypted_authorization_code", read_only=True)
    recipients = serializers.ListField(child=serializers.EmailField(), required=False)
    cc_recipients = serializers.ListField(child=serializers.EmailField(), required=False)

    class Meta:
        model = SMTPConfiguration
        fields = [
            "host", "port", "username", "from_email", "recipients", "cc_recipients", "use_tls", "enabled",
            "authorization_code", "authorization_code_configured", "updated_at",
        ]
        read_only_fields = ["authorization_code_configured", "updated_at"]

    def update(self, instance: SMTPConfiguration, validated_data: dict[str, object]) -> SMTPConfiguration:
        authorization_code = validated_data.pop("authorization_code", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if isinstance(authorization_code, str):
            instance.encrypted_authorization_code = encrypt_authorization_code(authorization_code)
        instance.save()
        return instance


class EmailDeliverySerializer(serializers.ModelSerializer[ReportEmailDelivery]):
    class Meta:
        model = ReportEmailDelivery
        fields = ["id", "report", "status", "recipients", "cc_recipients", "attempt_count", "error_message", "requested_by", "sent_at", "created_at"]
        read_only_fields = fields
