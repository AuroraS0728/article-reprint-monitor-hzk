from __future__ import annotations

import html
import ipaddress
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rapidfuzz import fuzz

from apps.accounts.models import User
from apps.articles.models import Article, ArticleIngestMethod, ArticleMonitoringStatus
from apps.articles.services import normalize_title
from apps.audit.models import OperationLog
from apps.core.redaction import safe_error_message
from apps.reposts.models import RepostRecord
from search_providers.base import SearchProvider
from search_providers.exceptions import SearchProviderError
from search_providers.registry import configured_search_provider
from search_providers.types import SearchCandidate

from .models import SearchRun, SearchRunStatus, Source

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "source",
}
TITLE_PUNCTUATION_RE = re.compile(r"[\s\t\r\n:：,，。.!！?？\"'“”‘’《》<>\-_\|—…·]+")


@dataclass(frozen=True)
class IngestArticleResult:
    article: Article
    created: bool
    updated: bool
    search_scheduled: bool


@dataclass(frozen=True)
class TitleMatch:
    matched: bool
    raw_score: float
    core_score: float
    similarity_score: float
    normalized_result_title: str


@dataclass(frozen=True)
class MonitoringLifecycle:
    monitor_started_at: datetime | None
    monitor_until: datetime
    retention_until: datetime
    monitoring_status: str
    next_search_at: datetime | None


def canonicalize_http_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise ValueError("链接必须是无凭据的绝对 HTTP(S) URL。")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("不允许 localhost 链接。")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("不允许使用裸 IP 地址。")
    port = parsed.port
    port_text = ""
    if port and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
        port_text = f":{port}"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunsplit((scheme, f"{hostname}{port_text}", parsed.path or "/", query, ""))


def source_item_key(source: Source, canonical_original_url: str) -> str:
    return sha256(f"{source.code}\n{canonical_original_url}".encode()).hexdigest()


def is_url_for_source(source: Source, url: str) -> bool:
    source_host = (urlsplit(source.base_url).hostname or "").lower().rstrip(".")
    source_host = source_host.removeprefix("www.")
    candidate_host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return bool(source_host and (candidate_host == source_host or candidate_host.endswith(f".{source_host}")))


def normalize_title_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).strip().lower()
    return TITLE_PUNCTUATION_RE.sub("", normalized)


def candidate_core_title(value: str, *, site_name: str = "", site_domain: str = "") -> str:
    core = unicodedata.normalize("NFKC", html.unescape(value)).strip()
    suffixes = [site_name.strip(), site_domain.strip()]
    for suffix in [item for item in suffixes if item]:
        pattern = re.compile(rf"\s*[-_|—]\s*{re.escape(suffix)}\s*$", re.IGNORECASE)
        updated = pattern.sub("", core).strip()
        if updated != core:
            return updated
    return core


def compare_titles(article_title: str, candidate: SearchCandidate) -> TitleMatch:
    expected = normalize_title_for_matching(article_title)
    raw = normalize_title_for_matching(candidate.title)
    core = normalize_title_for_matching(
        candidate_core_title(candidate.title, site_name=candidate.site_name, site_domain=candidate.domain)
    )
    raw_score = float(fuzz.ratio(expected, raw))
    core_score = float(fuzz.ratio(expected, core))
    score = max(raw_score, core_score)
    short_length = settings.SEARCH_SHORT_TITLE_LENGTH
    if len(expected) < short_length:
        matched = raw == expected or core == expected
    else:
        matched = score >= settings.SEARCH_SIMILARITY_THRESHOLD
    return TitleMatch(
        matched=matched,
        raw_score=raw_score,
        core_score=core_score,
        similarity_score=score,
        normalized_result_title=core,
    )


def _monitoring_fields(published_at: datetime, now: datetime) -> MonitoringLifecycle:
    monitor_until = published_at + timedelta(days=settings.ARTICLE_MONITOR_DAYS)
    retention_until = published_at + timedelta(days=settings.ARTICLE_RETENTION_DAYS)
    active = now < monitor_until
    return MonitoringLifecycle(
        monitor_started_at=now if active else None,
        monitor_until=monitor_until,
        retention_until=retention_until,
        monitoring_status=ArticleMonitoringStatus.ACTIVE if active else ArticleMonitoringStatus.COMPLETED,
        next_search_at=now if active else None,
    )


@transaction.atomic
def ingest_source_article(
    *, source: Source, title: str, author: str, published_at: datetime, original_url: str, created_by: User
) -> IngestArticleResult:
    canonical_url = canonicalize_http_url(original_url)
    if not is_url_for_source(source, canonical_url):
        raise ValueError("原文章 URL 不属于 Token 对应的原创来源。")
    key = source_item_key(source, canonical_url)
    now = timezone.now()
    local_published_at = timezone.localtime(published_at)
    lifecycle = _monitoring_fields(published_at, now)
    defaults = {
        "title": title,
        "normalized_title": normalize_title(title),
        "author": author,
        "published_at": published_at,
        "published_date": local_published_at.date(),
        "original_url": canonical_url,
        "source_platform": source.name,
        "author_department": author,
        "discovered_at": now,
        "ingest_method": ArticleIngestMethod.SOURCE_API,
        "created_by": created_by,
        "monitor_started_at": lifecycle.monitor_started_at,
        "monitor_until": lifecycle.monitor_until,
        "retention_until": lifecycle.retention_until,
        "monitoring_status": lifecycle.monitoring_status,
        "next_search_at": lifecycle.next_search_at,
    }
    article, created = Article.objects.select_for_update().get_or_create(
        source=source,
        source_item_key=key,
        defaults=defaults,
    )
    updated = False
    title_changed = False
    if not created:
        changes = {
            "title": title,
            "normalized_title": normalize_title(title),
            "author": author,
            "author_department": author,
            "published_at": published_at,
            "published_date": local_published_at.date(),
            "original_url": canonical_url,
        }
        title_changed = article.title != title
        update_fields: list[str] = []
        for field, value in changes.items():
            if getattr(article, field) != value:
                setattr(cast(Any, article), field, value)
                update_fields.append(field)
        if "published_at" in update_fields:
            lifecycle = _monitoring_fields(published_at, now)
            for field in ("monitor_until", "retention_until"):
                setattr(article, field, getattr(lifecycle, field))
                update_fields.append(field)
            if article.monitoring_status != ArticleMonitoringStatus.COMPLETED:
                article.monitoring_status = lifecycle.monitoring_status
                article.next_search_at = lifecycle.next_search_at
                update_fields.extend(["monitoring_status", "next_search_at"])
        if title_changed and article.monitoring_status == ArticleMonitoringStatus.ACTIVE:
            article.next_search_at = now
            if "next_search_at" not in update_fields:
                update_fields.append("next_search_at")
        if update_fields:
            article.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])
            updated = True
    search_scheduled = bool(article.monitoring_status == ArticleMonitoringStatus.ACTIVE and (created or title_changed))
    if search_scheduled:
        from .tasks import search_article_reposts

        transaction.on_commit(lambda: search_article_reposts.delay(article.id))
    return IngestArticleResult(article=article, created=created, updated=updated, search_scheduled=search_scheduled)


def _next_search_time(article: Article, now: datetime) -> datetime | None:
    if not article.monitor_until or now >= article.monitor_until:
        return None
    started = article.monitor_started_at or article.published_at or now
    elapsed_minutes = max(0, int((now - started).total_seconds() // 60))
    offsets = settings.ARTICLE_SEARCH_SCHEDULE_MINUTES
    next_offset = next((value for value in offsets if value > elapsed_minutes), None)
    candidate = started + timedelta(minutes=next_offset) if next_offset is not None else now + timedelta(hours=12)
    return min(candidate, article.monitor_until)


def _candidate_is_too_early(article: Article, candidate: SearchCandidate) -> bool:
    if not article.published_at or not candidate.published_at:
        return False
    return candidate.published_at < article.published_at - timedelta(
        hours=settings.SEARCH_PUBLISHED_TIME_TOLERANCE_HOURS
    )


@transaction.atomic
def upsert_global_repost(
    *, article: Article, candidate: SearchCandidate, match: TitleMatch, found_at: datetime
) -> tuple[RepostRecord, bool]:
    canonical_url = canonicalize_http_url(candidate.url)
    domain = (urlsplit(canonical_url).hostname or "").lower()
    url_hash = sha256(canonical_url.encode("utf-8")).hexdigest()
    defaults = {
        "platform": None,
        "site_name": candidate.site_name or domain,
        "site_domain": domain,
        "raw_url": candidate.url,
        "canonical_url": canonical_url,
        "canonical_url_hash": url_hash,
        "original_url": candidate.url,
        "normalized_url": canonical_url,
        "normalized_url_hash": url_hash,
        "final_url": canonical_url,
        "repost_title": candidate.title,
        "result_title": candidate.title,
        "normalized_result_title": match.normalized_result_title,
        "similarity_score": Decimal(str(round(match.similarity_score, 2))),
        "search_provider": candidate.provider,
        "repost_published_at": candidate.published_at,
        "result_published_at": candidate.published_at,
        "first_discovered_at": found_at,
        "first_found_at": found_at,
        "last_checked_at": found_at,
        "last_seen_at": found_at,
        "data_source": f"SEARCH_PROVIDER:{candidate.provider}",
    }
    try:
        with transaction.atomic():
            record, created = RepostRecord.objects.get_or_create(
                article=article,
                canonical_url_hash=url_hash,
                defaults=defaults,
            )
    except IntegrityError:
        record = RepostRecord.objects.select_for_update().get(article=article, canonical_url_hash=url_hash)
        created = False
    if created:
        OperationLog.objects.create(
            action_type="REPOST_DISCOVERED",
            target_type="RepostRecord",
            target_id=str(record.id),
            after_data={"article_id": article.id, "site_domain": domain, "similarity_score": match.similarity_score},
        )
        return record, True
    record.last_seen_at = found_at
    record.last_checked_at = found_at
    if record.similarity_score is None or match.similarity_score > float(record.similarity_score):
        record.similarity_score = Decimal(str(round(match.similarity_score, 2)))
        record.result_title = candidate.title
        record.repost_title = candidate.title
        record.normalized_result_title = match.normalized_result_title
    if not record.site_name:
        record.site_name = candidate.site_name or domain
    if not record.site_domain:
        record.site_domain = domain
    record.save(
        update_fields=[
            "last_seen_at",
            "last_checked_at",
            "similarity_score",
            "result_title",
            "repost_title",
            "normalized_result_title",
            "site_name",
            "site_domain",
            "updated_at",
        ]
    )
    return record, False


def search_article(article: Article, *, provider: SearchProvider | None = None) -> SearchRun:
    provider_instance = provider
    provider_code = getattr(provider_instance, "code", settings.SEARCH_PROVIDER or "unconfigured")
    queries = [f'"{article.title}"', article.title]
    run = SearchRun.objects.create(
        article=article,
        provider=provider_code,
        query=json.dumps(queries, ensure_ascii=False),
        status=SearchRunStatus.RUNNING,
        started_at=timezone.now(),
    )
    now = timezone.now()
    try:
        provider_instance = provider_instance or configured_search_provider()
        provider_code = provider_instance.code
        all_candidates: dict[str, SearchCandidate] = {}
        for query in queries:
            candidates = provider_instance.search(
                query,
                freshness_from=article.published_at,
                freshness_to=article.monitor_until,
                limit=settings.SEARCH_RESULT_LIMIT,
            )
            for candidate in candidates:
                try:
                    canonical = canonicalize_http_url(candidate.url)
                except ValueError:
                    continue
                all_candidates.setdefault(canonical, candidate)
        matched_count = 0
        new_count = 0
        for canonical, candidate in all_candidates.items():
            belongs_to_source = bool(article.source is not None and is_url_for_source(article.source, canonical))
            if belongs_to_source:
                continue
            if canonical == article.original_url or _candidate_is_too_early(article, candidate):
                continue
            match = compare_titles(article.title, candidate)
            if not match.matched:
                continue
            matched_count += 1
            _, created = upsert_global_repost(article=article, candidate=candidate, match=match, found_at=now)
            new_count += int(created)
        run.provider = provider_code
        run.status = SearchRunStatus.SUCCESS
        run.candidate_count = len(all_candidates)
        run.matched_count = matched_count
        run.new_repost_count = new_count
        run.completed_at = timezone.now()
        run.save()
        article.last_searched_at = run.completed_at
        article.next_search_at = _next_search_time(article, run.completed_at)
        if article.next_search_at is None:
            article.monitoring_status = ArticleMonitoringStatus.COMPLETED
        article.save(update_fields=["last_searched_at", "next_search_at", "monitoring_status", "updated_at"])
    except SearchProviderError as error:
        run.status = SearchRunStatus.ERROR
        run.error_code = error.code
        run.error_message = safe_error_message(error)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_code", "error_message", "completed_at"])
        article.last_searched_at = run.completed_at
        article.next_search_at = min(
            run.completed_at + timedelta(minutes=settings.SEARCH_ERROR_BACKOFF_MINUTES),
            article.monitor_until or run.completed_at,
        )
        article.save(update_fields=["last_searched_at", "next_search_at", "updated_at"])
    except Exception as error:
        run.status = SearchRunStatus.ERROR
        run.error_code = "SEARCH_PROVIDER_ERROR"
        run.error_message = safe_error_message(error)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_code", "error_message", "completed_at"])
        article.last_searched_at = run.completed_at
        article.next_search_at = min(
            run.completed_at + timedelta(minutes=settings.SEARCH_ERROR_BACKOFF_MINUTES),
            article.monitor_until or run.completed_at,
        )
        article.save(update_fields=["last_searched_at", "next_search_at", "updated_at"])
    return run


@transaction.atomic
def mark_repost_availability(*, record: RepostRecord, status: str, checked_at: datetime | None = None) -> None:
    if status not in {"UNKNOWN", "AVAILABLE", "UNAVAILABLE", "REMOVED"}:
        raise ValueError("无效的链接可用状态。")
    before = record.availability_status
    record.availability_status = status
    record.last_availability_checked_at = checked_at or timezone.now()
    record.save(update_fields=["availability_status", "last_availability_checked_at", "updated_at"])
    if before != status:
        OperationLog.objects.create(
            action_type="REPOST_AVAILABILITY_CHANGED",
            target_type="RepostRecord",
            target_id=str(record.id),
            before_data={"availability_status": before},
            after_data={"availability_status": status},
        )


def purge_expired_source_articles() -> dict[str, int]:
    now = timezone.now()
    details = {"articles_deleted": 0, "articles_retained_for_legacy": 0}
    expired_ids = list(Article.objects.filter(retention_until__lt=now).values_list("id", flat=True))
    from apps.monitoring.models import DetectionResult

    for article_id in expired_ids:
        if DetectionResult.objects.filter(article_id=article_id).exists():
            details["articles_retained_for_legacy"] += 1
            continue
        with transaction.atomic():
            RepostRecord.objects.filter(article_id=article_id).delete()
            SearchRun.objects.filter(article_id=article_id).delete()
            Article.objects.filter(id=article_id, retention_until__lt=now).delete()
            details["articles_deleted"] += 1
    return details
