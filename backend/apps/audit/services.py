from typing import Any

from rest_framework.request import Request

from apps.core.redaction import redact_sensitive

from .models import OperationLog


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
        before_data=redact_sensitive(before_data or {}),
        after_data=redact_sensitive(after_data or {}),
        request_id=request.headers.get("X-Request-ID", "")[:64],
        ip_address=ip_address or None,
    )
