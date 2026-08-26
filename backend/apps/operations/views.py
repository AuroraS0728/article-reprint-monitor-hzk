from __future__ import annotations

from typing import cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.core.permissions import IsAdministrator
from apps.core.redaction import redact_sensitive
from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.monitoring.models import DetectionBatch, TaskFailureLog
from apps.monitoring.serializers import DetectionBatchSerializer
from apps.platforms.models import Platform
from apps.platforms.serializers import PlatformSerializer

from .models import DatabaseBackup, MaintenanceRun
from .serializers import (
    DatabaseBackupSerializer,
    MaintenanceRunSerializer,
    SystemRuntimeConfigurationSerializer,
)
from .services import runtime_configuration
from .tasks import cleanup_expired_data_task, create_database_backup_task


class SystemRuntimeConfigurationView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = SystemRuntimeConfigurationSerializer

    def get(self, request: Request) -> Response:
        return ok(SystemRuntimeConfigurationSerializer(runtime_configuration()).data)

    def patch(self, request: Request) -> Response:
        configuration = runtime_configuration()
        before = SystemRuntimeConfigurationSerializer(configuration).data
        serializer = SystemRuntimeConfigurationSerializer(
            configuration, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        changed = serializer.save(updated_by=cast(User, request.user))
        record_audit(
            request,
            action_type="SYSTEM_RUNTIME_CONFIGURATION_UPDATE",
            target_type="SystemRuntimeConfiguration",
            target_id=changed.id,
            before_data=before,
            after_data=SystemRuntimeConfigurationSerializer(changed).data,
        )
        return ok(SystemRuntimeConfigurationSerializer(changed).data)


class RuntimeStatusView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = PlatformSerializer

    def get(self, request: Request) -> Response:
        return ok(
            {
                "platforms": PlatformSerializer(Platform.objects.all(), many=True).data,
                "latest_backup": (
                    DatabaseBackupSerializer(DatabaseBackup.objects.first()).data
                    if DatabaseBackup.objects.exists()
                    else None
                ),
                "latest_maintenance_run": (
                    MaintenanceRunSerializer(MaintenanceRun.objects.first()).data
                    if MaintenanceRun.objects.exists()
                    else None
                ),
            }
        )


class FailedDetectionBatchListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = DetectionBatchSerializer

    def get(self, request: Request) -> Response:
        return ok(
            DetectionBatchSerializer(
                DetectionBatch.objects.filter(status="FAILED")[:100], many=True
            ).data
        )


class TaskFailureLogListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        return ok(
            [
                {
                    "id": item.id,
                    "task_name": item.task_name,
                    "batch": item.batch_id,
                    "error_type": item.error_type,
                    "message": redact_sensitive(item.message),
                    "created_at": item.created_at,
                }
                for item in TaskFailureLog.objects.all()[:100]
            ]
        )


class MaintenanceRunListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = MaintenanceRunSerializer

    def get(self, request: Request) -> Response:
        return ok(
            MaintenanceRunSerializer(MaintenanceRun.objects.all()[:100], many=True).data
        )


class DatabaseBackupListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = DatabaseBackupSerializer

    def get(self, request: Request) -> Response:
        return ok(
            DatabaseBackupSerializer(DatabaseBackup.objects.all()[:100], many=True).data
        )


class MaintenanceActionView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = EmptySerializer

    def post(self, request: Request, action: str) -> Response:
        if action == "cleanup":
            cleanup_expired_data_task.delay()
            action_type = "SYSTEM_MAINTENANCE_CLEANUP_REQUEST"
        elif action == "backup":
            create_database_backup_task.delay()
            action_type = "SYSTEM_DATABASE_BACKUP_REQUEST"
        else:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "不支持的维护操作。",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(request, action_type=action_type, target_type="SystemMaintenance")
        return ok({"queued": True}, status.HTTP_202_ACCEPTED)
