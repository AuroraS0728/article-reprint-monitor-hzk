from __future__ import annotations

import hmac
from typing import cast

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.request import Request

from apps.accounts.models import User

from .models import SourceIngestToken
from .token_services import hash_source_token


class SourceTokenAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request: Request) -> tuple[User, SourceIngestToken] | None:
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if parts[0].lower() != self.keyword or len(parts) != 2:
            raise exceptions.AuthenticationFailed("Source API 需要 Bearer Token。", code="invalid_token")
        try:
            plaintext = parts[1].decode("ascii")
        except UnicodeDecodeError as error:
            raise exceptions.AuthenticationFailed("Bearer Token 格式无效。", code="invalid_token") from error
        digest = hash_source_token(plaintext)
        token = SourceIngestToken.objects.select_related("source", "created_by").filter(token_hash=digest).first()
        if token is None or not hmac.compare_digest(token.token_hash, digest):
            raise exceptions.AuthenticationFailed("Bearer Token 无效。", code="invalid_token")
        now = timezone.now()
        if not token.is_active:
            raise exceptions.AuthenticationFailed("Bearer Token 已停用。", code="inactive_token")
        if token.expires_at and token.expires_at <= now:
            raise exceptions.AuthenticationFailed("Bearer Token 已过期。", code="expired_token")
        if not token.source.is_active:
            raise exceptions.AuthenticationFailed("原创来源已停用。", code="inactive_source")
        token.last_used_at = now
        token.save(update_fields=["last_used_at"])
        return cast(User, token.created_by), token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
