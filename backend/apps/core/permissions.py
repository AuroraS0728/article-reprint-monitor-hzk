from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.accounts.models import Role


class IsAdministrator(BasePermission):
    message = "需要管理员权限。"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            getattr(request, "user", None)
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == Role.ADMIN)
        )


class CanOperate(BasePermission):
    message = "需要管理员或操作人员权限。"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            getattr(request, "user", None)
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.role in {Role.ADMIN, Role.OPERATOR}
            )
        )
