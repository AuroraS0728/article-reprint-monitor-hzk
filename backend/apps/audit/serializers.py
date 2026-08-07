from rest_framework import serializers

from apps.core.redaction import redact_sensitive

from .models import OperationLog


class OperationLogSerializer(serializers.ModelSerializer[OperationLog]):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = OperationLog
        fields = [
            "id",
            "actor_username",
            "action_type",
            "target_type",
            "target_id",
            "before_data",
            "after_data",
            "request_id",
            "ip_address",
            "created_at",
        ]

    def to_representation(self, instance: OperationLog) -> dict[str, object]:
        return redact_sensitive(super().to_representation(instance))
