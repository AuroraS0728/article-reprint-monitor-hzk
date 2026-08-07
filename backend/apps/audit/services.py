from typing import Any

from rest_framework.request import Request

from .models import OperationLog

SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "cookie", "smtp_password"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def record_audit(
    request: Request,
    *,
    action_type: str,
    target_type: str,
    target_id: int | str = "",
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
) -> None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    OperationLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action_type=action_type,
        target_type=target_type,
        target_id=str(target_id),
        before_data=_redact(before_data or {}),
        after_data=_redact(after_data or {}),
        request_id=request.headers.get("X-Request-ID", "")[:64],
        ip_address=ip_address or None,
    )
