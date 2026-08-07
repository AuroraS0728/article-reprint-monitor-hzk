from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import transaction
from django.utils import timezone

from apps.articles.models import Article
from apps.articles.services import normalize_title
from apps.platforms.models import Platform
from apps.reposts.models import RepostRecord

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


def normalize_repost_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname:
        raise ValueError("转载链接必须是绝对 HTTP(S) URL。")
    port = (
        f":{parsed.port}"
        if parsed.port
        and not (scheme == "https" and parsed.port == 443)
        and not (scheme == "http" and parsed.port == 80)
        else ""
    )
    path = parsed.path or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        )
    )
    return urlunsplit((scheme, f"{hostname}{port}", path, query, ""))


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
    for candidate in matching:
        upsert_repost_record(article=article, platform=platform, candidate=candidate, checked_at=result.completed_at)
    return result


@transaction.atomic
def upsert_repost_record(
    *, article: Article, platform: Platform, candidate: SearchCandidate, checked_at: datetime
) -> RepostRecord:
    normalized_url = normalize_repost_url(candidate.final_url or candidate.original_url)
    normalized_url_hash = sha256(normalized_url.encode()).hexdigest()
    record, created = RepostRecord.objects.get_or_create(
        article=article,
        platform=platform,
        normalized_url_hash=normalized_url_hash,
        defaults={
            "normalized_url": normalized_url,
            "original_url": candidate.original_url,
            "final_url": candidate.final_url,
            "repost_title": candidate.title,
            "repost_published_at": candidate.published_at,
            "first_discovered_at": checked_at,
            "last_checked_at": checked_at,
            "data_source": candidate.data_source,
        },
    )
    if not created:
        record.normalized_url = normalized_url
        record.original_url = candidate.original_url
        record.final_url = candidate.final_url
        record.repost_title = candidate.title
        record.repost_published_at = candidate.published_at
        record.last_checked_at = checked_at
        record.data_source = candidate.data_source
        record.save()
    return record
