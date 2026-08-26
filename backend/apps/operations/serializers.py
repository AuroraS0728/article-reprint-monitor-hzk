from rest_framework import serializers

from .models import DatabaseBackup, MaintenanceRun, SystemRuntimeConfiguration


class SystemRuntimeConfigurationSerializer(
    serializers.ModelSerializer[SystemRuntimeConfiguration]
):
    class Meta:
        model = SystemRuntimeConfiguration
        fields = [
            "maintenance_enabled",
            "database_backup_enabled",
            "updated_by",
            "updated_at",
        ]
        read_only_fields = ["updated_by", "updated_at"]


class MaintenanceRunSerializer(serializers.ModelSerializer[MaintenanceRun]):
    class Meta:
        model = MaintenanceRun
        fields = [
            "id",
            "operation_name",
            "status",
            "details",
            "error_message",
            "started_at",
            "completed_at",
        ]
        read_only_fields = fields


class DatabaseBackupSerializer(serializers.ModelSerializer[DatabaseBackup]):
    class Meta:
        model = DatabaseBackup
        fields = [
            "id",
            "status",
            "file_sha256",
            "size_bytes",
            "error_message",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields
