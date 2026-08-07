from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

REDACTED = "[REDACTED]"
REDACTED_URL = "[REDACTED_URL]"
URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", flags=re.IGNORECASE)
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|token|authorization|cookie|session|jwt|secret|"
    r"access[_ -]?key|api[_ -]?key|credential)\s*[:=]\s*[^\s,;]+"
)
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "smtp",
    "authorization",
    "authcode",
    "token",
    "cookie",
    "session",
    "jwt",
    "secret",
    "accesskey",
    "access_key",
    "apikey",
    "api_key",
    "signature",
    "credential",
    "sign",
    "databasepassword",
    "dbpassword",
)


def is_sensitive_key(key: object) -> bool:
    normalized = "".join(character for character in str(key).lower() if character.isalnum() or character == "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def contains_sensitive_url_data(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None:
        return True
    return any(is_sensitive_key(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True))


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): REDACTED if is_sensitive_key(key) else redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        if contains_sensitive_url_data(value):
            return REDACTED_URL
        value = URL_PATTERN.sub(
            lambda match: REDACTED_URL if contains_sensitive_url_data(match.group(0)) else match.group(0), value
        )
        return INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    return value


def safe_error_message(error: object, *, limit: int = 1000) -> str:
    redacted = redact_sensitive(str(error))
    return str(redacted)[:limit]
