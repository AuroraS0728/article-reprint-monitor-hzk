from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from apps.accounts.models import User

from .models import Source, SourceIngestToken


@dataclass(frozen=True)
class CreatedSourceToken:
    record: SourceIngestToken
    plaintext: str


def hash_source_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_source_token(
    *, source: Source, name: str, created_by: User, expires_at: datetime | None = None
) -> CreatedSourceToken:
    plaintext = secrets.token_urlsafe(48)
    record = SourceIngestToken.objects.create(
        source=source,
        name=name.strip(),
        token_prefix=plaintext[:12],
        token_hash=hash_source_token(plaintext),
        created_by=created_by,
        expires_at=expires_at,
    )
    return CreatedSourceToken(record=record, plaintext=plaintext)
