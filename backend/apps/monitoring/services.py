from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.articles.models import Article
from apps.articles.services import normalize_title
from apps.platforms.models import Platform
from apps.reposts.models import RepostRecord
from apps.sources.services import canonicalize_http_url

from .models import DetectionResult, PlatformDetectionStatus


@dataclass(frozen=True)
class SearchCandidate:
    original_url: str
    final_url: str
    title: str
    published_at: datetime | None
    data_source: str


@dataclass(frozen=True)
class SearchOutcome:
    request_success: bool
    completed: bool
    candidates: tuple[SearchCandidate, ...] = ()
    reason_code: str = ""
    reason_message: str = ""
    login_required: bool = False
    captcha_detected: bool = False
    final_status: str = "UNKNOWN"


class PlatformAdapter(Protocol):
    def search_exact_title(self, *, article: Article, platform: Platform) -> SearchOutcome: ...


class AdapterNotValidatedError(RuntimeError):
    pass


def update_platform_runtime_status(*, platform: Platform, succeeded: bool, failure_reason: str = "") -> None:
    now = timezone.now()
    if succeeded:
        platform.last_success_at = now
        platform.consecutive_failure_count = 0
        platform.last_failure_reason = ""
        platform.save(
            update_fields=["last_success_at", "consecutive_failure_count", "last_failure_reason", "updated_at"]
        )
        return
    platform.last_failure_at = now
    platform.consecutive_failure_count += 1
    platform.last_failure_reason = failure_reason[:500]
    platform.save(update_fields=["last_failure_at", "consecutive_failure_count", "last_failure_reason", "updated_at"])


def normalize_repost_url(value: str) -> str:
    return canonicalize_http_url(value)


def no_validated_adapter(*, article: Article, platform: Platform) -> SearchOutcome:
    return SearchOutcome(
        request_success=False,
        completed=False,
        reason_code="ADAPTER_NOT_VALIDATED",
        reason_message="平台适配器尚未完成真实本机验证。",
        final_status="UNKNOWN",
    )


def evaluate_detection(*, result: DetectionResult, adapter: PlatformAdapter | None = None) -> DetectionResult:
    article = result.article
    platform = result.platform
    if RepostRecord.objects.filter(article=article, platform=platform, is_valid=True).exists():
        now = timezone.now()
        result.status = PlatformDetectionStatus.FOUND
        result.reason_code = "HISTORICAL_REPOST"
        result.reason_message = ""
        result.started_at = now
        result.completed_at = now
        result.save(
            update_fields=[
                "status",
                "reason_code",
                "reason_message",
                "started_at",
                "completed_at",
                "updated_at",
            ]
        )
        return result

    result.attempt_count += 1
    result.started_at = timezone.now()
    search = (
        adapter.search_exact_title(article=article, platform=platform)
        if adapter
        else no_validated_adapter(article=article, platform=platform)
    )
    if not search.completed:
        result.status = PlatformDetectionStatus.UNKNOWN
        result.reason_code = search.reason_code or "SEARCH_UNCONFIRMED"
        result.reason_message = search.reason_message or "搜索结果状态无法确认。"
        result.completed_at = timezone.now()
        result.save(
            update_fields=[
                "status",
                "reason_code",
                "reason_message",
                "attempt_count",
                "started_at",
                "completed_at",
                "updated_at",
            ]
        )
        update_platform_runtime_status(
            platform=platform,
            succeeded=False,
            failure_reason=result.reason_code or result.reason_message,
        )
        return result

    confirmed_suffixes = tuple(platform.confirmed_title_suffixes)
    expected_title = normalize_title(article.title, confirmed_suffixes=confirmed_suffixes)
    matching = [
        candidate
        for candidate in search.candidates
        if normalize_title(candidate.title, confirmed_suffixes=confirmed_suffixes) == expected_title
    ]
    result.status = PlatformDetectionStatus.FOUND if matching else PlatformDetectionStatus.NOT_FOUND
    result.reason_code = ""
    result.reason_message = ""
    result.completed_at = timezone.now()
    result.save(
        update_fields=[
            "status",
            "reason_code",
            "reason_message",
            "attempt_count",
            "started_at",
            "completed_at",
            "updated_at",
        ]
    )
    update_platform_runtime_status(platform=platform, succeeded=True)
    for candidate in matching:
        upsert_repost_record(article=article, platform=platform, candidate=candidate, checked_at=result.completed_at)
    return result


@transaction.atomic
def upsert_repost_record(
    *, article: Article, platform: Platform, candidate: SearchCandidate, checked_at: datetime
) -> RepostRecord:
    normalized_url = normalize_repost_url(candidate.final_url or candidate.original_url)
    normalized_url_hash = sha256(normalized_url.encode()).hexdigest()
    domain_row = platform.domains.first()
    record, created = RepostRecord.objects.get_or_create(
        article=article,
        canonical_url_hash=normalized_url_hash,
        defaults={
            "platform": platform,
            "site_name": platform.name,
            "site_domain": domain_row.domain if domain_row else "",
            "raw_url": candidate.original_url,
            "canonical_url": normalized_url,
            "canonical_url_hash": normalized_url_hash,
            "normalized_url": normalized_url,
            "normalized_url_hash": normalized_url_hash,
            "original_url": candidate.original_url,
            "final_url": candidate.final_url,
            "repost_title": candidate.title,
            "result_title": candidate.title,
            "normalized_result_title": normalize_title(candidate.title),
            "repost_published_at": candidate.published_at,
            "result_published_at": candidate.published_at,
            "first_discovered_at": checked_at,
            "first_found_at": checked_at,
            "last_checked_at": checked_at,
            "last_seen_at": checked_at,
            "data_source": candidate.data_source,
        },
    )
    if not created:
        if record.is_manual_supplement:
            record.last_checked_at = checked_at
            record.save(update_fields=["last_checked_at", "updated_at"])
            return record
        record.normalized_url = normalized_url
        record.canonical_url = normalized_url
        record.raw_url = candidate.original_url
        record.original_url = candidate.original_url
        record.final_url = candidate.final_url
        record.repost_title = candidate.title
        record.repost_published_at = candidate.published_at
        record.last_checked_at = checked_at
        record.last_seen_at = checked_at
        record.data_source = candidate.data_source
        record.save()
    return record
