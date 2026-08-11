from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SearchCandidate:
    title: str
    url: str
    snippet: str = ""
    display_url: str = ""
    domain: str = ""
    published_at: datetime | None = None
    provider: str = ""
    site_name: str = ""
    raw_data: dict[str, object] = field(default_factory=dict)
