from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from apps.audit.services import record_audit
from apps.core.permissions import IsAdministrator
from apps.core.views import ok

from .models import Platform, PlatformStatus
from .serializers import PlatformSerializer


class PlatformListCreateView(generics.ListCreateAPIView[Platform]):
    serializer_class = PlatformSerializer
    queryset = Platform.objects.prefetch_related("domains").all()

    def get_permissions(self) -> Sequence[BasePermission]:
        return [IsAdministrator()] if self.request.method == "POST" else [permissions.IsAuthenticated()]

    def perform_create(self, serializer: BaseSerializer[Platform]) -> None:
        platform = cast(Platform, serializer.save())
        record_audit(
            self.request,
            action_type="PLATFORM_CREATE",
            target_type="platform",
            target_id=platform.id,
            after_data=PlatformSerializer(platform).data,
        )


class PlatformDetailView(generics.RetrieveUpdateAPIView[Platform]):
    serializer_class = PlatformSerializer
    queryset = Platform.objects.prefetch_related("domains").all()
    permission_classes = [IsAdministrator]

    def perform_update(self, serializer: BaseSerializer[Platform]) -> None:
        before = PlatformSerializer(self.get_object()).data
        platform = cast(Platform, serializer.save())
        record_audit(
            self.request,
            action_type="PLATFORM_UPDATE",
            target_type="platform",
            target_id=platform.id,
            before_data=before,
            after_data=PlatformSerializer(platform).data,
        )


class PlatformActionView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = PlatformSerializer

    @extend_schema(operation_id="platform_action")
    def post(self, request: Request, pk: int, action: str) -> Response:
        platform = Platform.objects.get(pk=pk)
        before = PlatformSerializer(platform).data
        if action == "enable":
            if platform.last_verified_at is None:
                return Response(
                    {
                        "success": False,
                        "error": {"code": "PLATFORM_NOT_READY", "message": "没有真实验证记录，不能启用平台。"},
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            platform.status = PlatformStatus.ENABLED
        elif action == "disable":
            platform.status = PlatformStatus.DISABLED
        elif action == "archive":
            platform.status = PlatformStatus.ARCHIVED
        else:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "不支持的平台动作。"}}, status=400
            )
        platform.save(update_fields=["status", "updated_at"])
        record_audit(
            request,
            action_type=f"PLATFORM_{action.upper()}",
            target_type="platform",
            target_id=platform.id,
            before_data=before,
            after_data=PlatformSerializer(platform).data,
        )
        return ok(PlatformSerializer(platform).data)
