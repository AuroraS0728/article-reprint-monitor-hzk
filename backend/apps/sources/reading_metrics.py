"""Reserved integration boundary for approved owned-channel reading metrics.

This module deliberately contains no browser scraping or platform-specific client.
An approved provider can implement the protocol later; until then callers expose
``None`` and ``接口待接入`` rather than inventing a numeric reading count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ReadingMetric:
    publication_url: str
    reading_count: int | None
    observed_at: datetime | None
    status: str


class ReadingMetricProvider(Protocol):
    code: str

    def fetch(self, *, publication_url: str) -> ReadingMetric:
        """Fetch one approved metric without credentials leaking into logs."""
