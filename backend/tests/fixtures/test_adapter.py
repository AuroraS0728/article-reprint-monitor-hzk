from datetime import datetime

from apps.monitoring.services import PlatformAdapter, SearchCandidate, SearchOutcome


class FixtureAdapter(PlatformAdapter):
    """Deterministic adapter used only to verify business rules, not a platform adapter."""

    def __init__(self, *, completed: bool, candidates: tuple[SearchCandidate, ...] = ()) -> None:
        self.completed = completed
        self.candidates = candidates

    def search_exact_title(self, *, article: object, platform: object) -> SearchOutcome:
        return SearchOutcome(
            request_success=self.completed,
            completed=self.completed,
            candidates=self.candidates,
            reason_code="FIXTURE_UNCONFIRMED" if not self.completed else "",
            reason_message="fixture response is intentionally unconfirmed" if not self.completed else "",
            final_status="COMPLETED" if self.completed else "UNKNOWN",
        )


def candidate(*, url: str, title: str, published_at: datetime | None = None) -> SearchCandidate:
    return SearchCandidate(
        original_url=url,
        final_url=url,
        title=title,
        published_at=published_at,
        data_source="tests.fixture",
    )
