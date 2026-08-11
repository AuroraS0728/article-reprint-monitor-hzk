from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .types import SearchCandidate


class SearchProvider(Protocol):
    code: str

    def search(
        self,
        query: str,
        *,
        freshness_from: datetime | None = None,
        freshness_to: datetime | None = None,
        limit: int | None = None,
    ) -> list[SearchCandidate]: ...
