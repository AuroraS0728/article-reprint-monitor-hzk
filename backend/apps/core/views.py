from typing import Any, cast

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit.services import record_audit

from .permissions import IsAdministrator
from .serializers import (
    ChangePasswordSerializer,
    CurrentUserSerializer,
    EmptySerializer,
    LoginSerializer,
    UserManagementSerializer,
)


def ok(data: Any, status_code: int = status.HTTP_200_OK) -> Response:
    return Response({"success": True, "data": data}, status=status_code)


class HealthView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        return ok({"status": "ok"})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def get(self, request: Request) -> Response:
        return ok({"csrf_token": get_token(request)})

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            record_audit(request, action_type="LOGIN_FAILED", target_type="user", target_id=username)
            return Response(
                {"success": False, "error": {"code": "AUTH_INVALID", "message": "用户名或密码错误"}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        record_audit(request, action_type="LOGIN_SUCCESS", target_type="user", target_id=user.id)
        return ok({"id": user.id, "username": user.username, "role": user.role})


class LogoutView(APIView):
    serializer_class = EmptySerializer

    def post(self, request: Request) -> Response:
        if request.user.is_authenticated:
            record_audit(request, action_type="LOGOUT", target_type="user", target_id=request.user.id)
        logout(request)
        return ok({})


class MeView(APIView):
    serializer_class = CurrentUserSerializer

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        return ok(
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "must_change_password": user.must_change_password,
            }
        )


class ChangePasswordView(APIView):
    serializer_class = ChangePasswordSerializer

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"success": False, "error": {"code": "AUTH_INVALID", "message": "当前密码不正确。"}}, status=400
            )
        validate_password(serializer.validated_data["new_password"], user=user)
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        record_audit(request, action_type="PASSWORD_CHANGE", target_type="user", target_id=user.id)
        return ok({})


class UserListCreateView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = UserManagementSerializer

    def get(self, request: Request) -> Response:
        return ok(UserManagementSerializer(User.objects.all().order_by("username"), many=True).data)

    def post(self, request: Request) -> Response:
        serializer = UserManagementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record_audit(
            request,
            action_type="USER_CREATE",
            target_type="user",
            target_id=user.id,
            after_data=UserManagementSerializer(user).data,
        )
        return ok(UserManagementSerializer(user).data, status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = UserManagementSerializer

    def patch(self, request: Request, pk: int) -> Response:
        user = get_object_or_404(User, pk=pk)
        before = UserManagementSerializer(user).data
        serializer = UserManagementSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = serializer.save()
        record_audit(
            request,
            action_type="USER_UPDATE",
            target_type="user",
            target_id=user.id,
            before_data=before,
            after_data=UserManagementSerializer(changed).data,
        )
        return ok(UserManagementSerializer(changed).data)
