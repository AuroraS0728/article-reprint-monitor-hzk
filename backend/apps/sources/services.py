from __future__ import annotations

import hmac
import html
import ipaddress
import json
import re
import secrets
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
from apps.articles.services import (
    ArticleDuplicateError,
    create_approved_duplicate,
    create_standard_article,
    normalize_title,
)
from apps.audit.models import OperationLog
from apps.core.redaction import safe_error_message
from apps.reposts.models import ContentRelation, RepostRecord
from search_providers.base import SearchProvider
from search_providers.exceptions import SearchProviderError
from search_providers.registry import configured_search_provider, search_provider_for_code
from search_providers.types import SearchCandidate

from .models import (
    ArticleIngestConflict,
    ArticleIngestConflictStatus,
    OwnedChannel,
    SearchCandidateDisposition,
    SearchProviderConfiguration,
    SearchRun,
    SearchRunCandidate,
    SearchRunStatus,
    Source,
    SourceIngestToken,
    TargetedCrawlTask,
    TargetedCrawlTaskStatus,
)

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
    article: Article | None
    created: bool
    updated: bool
    search_scheduled: bool
    pending_review: bool = False
    conflict: ArticleIngestConflict | None = None
    conflict_created: bool = False
    reason_code: str = ""


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
        monitoring_status=(ArticleMonitoringStatus.ACTIVE if active else ArticleMonitoringStatus.COMPLETED),
        next_search_at=now if active else None,
    )


def _source_article_data(
    *,
    source: Source,
    title: str,
    author: str,
    published_at: datetime,
    canonical_url: str,
    key: str,
    now: datetime,
    channel_code: str = "",
    channel_name: str = "",
    section_code: str = "",
    section_name: str = "",
) -> dict[str, Any]:
    lifecycle = _monitoring_fields(published_at, now)
    return {
        "title": title,
        "author": author,
        "published_at": published_at,
        "published_date": timezone.localtime(published_at).date(),
        "original_url": canonical_url,
        "source_platform": source.name,
        "author_department": author,
        "channel_code": channel_code,
        "channel_name": channel_name,
        "section_code": section_code,
        "section_name": section_name,
        "discovered_at": now,
        "ingest_method": ArticleIngestMethod.SOURCE_API,
        "source": source,
        "source_item_key": key,
        "monitor_started_at": lifecycle.monitor_started_at,
        "monitor_until": lifecycle.monitor_until,
        "retention_until": lifecycle.retention_until,
        "monitoring_status": lifecycle.monitoring_status,
        "next_search_at": lifecycle.next_search_at,
    }


def _update_existing_source_article(
    *,
    article: Article,
    title: str,
    author: str,
    published_at: datetime,
    canonical_url: str,
    now: datetime,
    channel_code: str = "",
    channel_name: str = "",
    section_code: str = "",
    section_name: str = "",
) -> tuple[bool, bool]:
    updated = False
    changes = {
        "title": title,
        "normalized_title": normalize_title(title),
        "author": author,
        "author_department": author,
        "published_at": published_at,
        "published_date": timezone.localtime(published_at).date(),
        "original_url": canonical_url,
        "channel_code": channel_code,
        "channel_name": channel_name,
        "section_code": section_code,
        "section_name": section_name,
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
    return updated, title_changed


def _schedule_source_search(article: Article, *, should_schedule: bool) -> bool:
    search_scheduled = bool(article.monitoring_status == ArticleMonitoringStatus.ACTIVE and should_schedule)
    if search_scheduled:
        from .tasks import search_article_reposts

        transaction.on_commit(lambda: search_article_reposts.delay(article.id))
    return search_scheduled


def _pending_conflict_result(conflict: ArticleIngestConflict, *, created: bool) -> IngestArticleResult:
    return IngestArticleResult(
        article=None,
        created=False,
        updated=False,
        search_scheduled=False,
        pending_review=True,
        conflict=conflict,
        conflict_created=created,
        reason_code="DUPLICATE_REVIEW_REQUIRED",
    )


def _create_or_reuse_source_conflict(
    *,
    source: Source,
    existing_article: Article,
    title: str,
    author: str,
    published_at: datetime,
    canonical_url: str,
    key: str,
    created_by: User,
) -> IngestArticleResult:
    conflict, created = ArticleIngestConflict.objects.get_or_create(
        source=source,
        source_item_key=key,
        defaults={
            "existing_article": existing_article,
            "title": title,
            "normalized_title": normalize_title(title),
            "author": author,
            "published_at": published_at,
            "published_date": timezone.localtime(published_at).date(),
            "original_url": canonical_url,
            "canonical_original_url": canonical_url,
            "created_by": created_by,
        },
    )
    if not created and conflict.status == ArticleIngestConflictStatus.PENDING:
        conflict.existing_article = existing_article
        conflict.title = title
        conflict.normalized_title = normalize_title(title)
        conflict.author = author
        conflict.published_at = published_at
        conflict.published_date = timezone.localtime(published_at).date()
        conflict.original_url = canonical_url
        conflict.canonical_original_url = canonical_url
        conflict.save(
            update_fields=[
                "existing_article",
                "title",
                "normalized_title",
                "author",
                "published_at",
                "published_date",
                "original_url",
                "canonical_original_url",
                "updated_at",
            ]
        )
    return _pending_conflict_result(conflict, created=created)


@transaction.atomic
def ingest_source_article(
    *,
    source: Source,
    title: str,
    author: str,
    published_at: datetime,
    original_url: str,
    created_by: User,
    channel_code: str = "",
    channel_name: str = "",
    section_code: str = "",
    section_name: str = "",
) -> IngestArticleResult:
    canonical_url = canonicalize_http_url(original_url)
    if not is_url_for_source(source, canonical_url):
        raise ValueError("原文章 URL 不属于 Token 对应的原创来源。")
    key = source_item_key(source, canonical_url)
    now = timezone.now()
    normalized_title = normalize_title(title)
    published_date = timezone.localtime(published_at).date()

    article = Article.objects.select_for_update().filter(source=source, source_item_key=key).first()
    if article is not None:
        updated, title_changed = _update_existing_source_article(
            article=article,
            title=title,
            author=author,
            published_at=published_at,
            canonical_url=canonical_url,
            now=now,
            channel_code=channel_code,
            channel_name=channel_name,
            section_code=section_code,
            section_name=section_name,
        )
        return IngestArticleResult(
            article=article,
            created=False,
            updated=updated,
            search_scheduled=_schedule_source_search(article, should_schedule=title_changed),
        )

    prior_conflict = (
        ArticleIngestConflict.objects.select_for_update()
        .select_related("created_article", "linked_article")
        .filter(source=source, source_item_key=key)
        .first()
    )
    if prior_conflict is not None:
        if prior_conflict.status == ArticleIngestConflictStatus.PENDING:
            return _create_or_reuse_source_conflict(
                source=source,
                existing_article=prior_conflict.existing_article,
                title=title,
                author=author,
                published_at=published_at,
                canonical_url=canonical_url,
                key=key,
                created_by=created_by,
            )
        resolved_article = prior_conflict.created_article or prior_conflict.linked_article
        return IngestArticleResult(
            article=resolved_article,
            created=False,
            updated=False,
            search_scheduled=False,
            conflict=prior_conflict,
            reason_code=prior_conflict.status,
        )

    duplicate = (
        Article.objects.select_for_update()
        .filter(normalized_title=normalized_title, published_date=published_date)
        .order_by("duplicate_slot", "id")
        .first()
    )
    if duplicate is not None:
        return _create_or_reuse_source_conflict(
            source=source,
            existing_article=duplicate,
            title=title,
            author=author,
            published_at=published_at,
            canonical_url=canonical_url,
            key=key,
            created_by=created_by,
        )

    article_data = _source_article_data(
        source=source,
        title=title,
        author=author,
        published_at=published_at,
        canonical_url=canonical_url,
        key=key,
        now=now,
        channel_code=channel_code,
        channel_name=channel_name,
        section_code=section_code,
        section_name=section_name,
    )
    try:
        article = create_standard_article(data=article_data, created_by=created_by)
    except ArticleDuplicateError:
        article = Article.objects.filter(source=source, source_item_key=key).first()
        if article is not None:
            updated, title_changed = _update_existing_source_article(
                article=article,
                title=title,
                author=author,
                published_at=published_at,
                canonical_url=canonical_url,
                now=now,
                channel_code=channel_code,
                channel_name=channel_name,
                section_code=section_code,
                section_name=section_name,
            )
            return IngestArticleResult(
                article=article,
                created=False,
                updated=updated,
                search_scheduled=_schedule_source_search(article, should_schedule=title_changed),
            )
        duplicate = Article.objects.filter(
            normalized_title=normalized_title,
            published_date=published_date,
        ).first()
        if duplicate is None:
            raise
        return _create_or_reuse_source_conflict(
            source=source,
            existing_article=duplicate,
            title=title,
            author=author,
            published_at=published_at,
            canonical_url=canonical_url,
            key=key,
            created_by=created_by,
        )
    except IntegrityError:
        article = Article.objects.filter(source=source, source_item_key=key).first()
        if article is None:
            raise
        updated, title_changed = _update_existing_source_article(
            article=article,
            title=title,
            author=author,
            published_at=published_at,
            canonical_url=canonical_url,
            now=now,
            channel_code=channel_code,
            channel_name=channel_name,
            section_code=section_code,
            section_name=section_name,
        )
        return IngestArticleResult(
            article=article,
            created=False,
            updated=updated,
            search_scheduled=_schedule_source_search(article, should_schedule=title_changed),
        )
    return IngestArticleResult(
        article=article,
        created=True,
        updated=False,
        search_scheduled=_schedule_source_search(article, should_schedule=True),
    )


def approve_source_ingest_conflict(
    *, conflict_id: int, approved_by: User, review_reason: str
) -> tuple[ArticleIngestConflict, Article]:
    reason = review_reason.strip()
    if not reason:
        raise ValueError("审核原因不能为空。")
    with transaction.atomic():
        conflict = ArticleIngestConflict.objects.select_for_update().select_related("source").get(pk=conflict_id)
        if conflict.status != ArticleIngestConflictStatus.PENDING:
            raise ValueError("该 Source Ingest Conflict 已处理。")
        now = timezone.now()
        article_data = _source_article_data(
            source=conflict.source,
            title=conflict.title,
            author=conflict.author,
            published_at=conflict.published_at,
            canonical_url=conflict.canonical_original_url,
            key=conflict.source_item_key,
            now=now,
        )
        article = create_approved_duplicate(
            data=article_data,
            approved_by=approved_by,
            duplicate_reason=reason,
        )
        conflict.status = ArticleIngestConflictStatus.APPROVED_AS_NEW
        conflict.created_article = article
        conflict.reviewed_by = approved_by
        conflict.reviewed_at = now
        conflict.review_reason = reason
        conflict.save(
            update_fields=[
                "status",
                "created_article",
                "reviewed_by",
                "reviewed_at",
                "review_reason",
                "updated_at",
            ]
        )
        _schedule_source_search(article, should_schedule=True)
        return conflict, article


def link_source_ingest_conflict(
    *, conflict_id: int, linked_article: Article, reviewed_by: User, review_reason: str
) -> ArticleIngestConflict:
    reason = review_reason.strip()
    if not reason:
        raise ValueError("审核原因不能为空。")
    with transaction.atomic():
        conflict = ArticleIngestConflict.objects.select_for_update().get(pk=conflict_id)
        if conflict.status != ArticleIngestConflictStatus.PENDING:
            raise ValueError("该 Source Ingest Conflict 已处理。")
        if (
            linked_article.normalized_title != conflict.normalized_title
            or linked_article.published_date != conflict.published_date
        ):
            raise ValueError("只能关联同日同标准化标题的 Article。")
        conflict.status = ArticleIngestConflictStatus.LINKED_TO_EXISTING
        conflict.linked_article = linked_article
        conflict.reviewed_by = reviewed_by
        conflict.reviewed_at = timezone.now()
        conflict.review_reason = reason
        conflict.save(
            update_fields=[
                "status",
                "linked_article",
                "reviewed_by",
                "reviewed_at",
                "review_reason",
                "updated_at",
            ]
        )
        return conflict


def _next_search_time(article: Article, now: datetime) -> datetime | None:
    if not article.monitor_until or now >= article.monitor_until:
        return None
    started = article.monitor_started_at or article.published_at or now
    elapsed_minutes = max(0, int((now - started).total_seconds() // 60))
    offsets = settings.ARTICLE_SEARCH_SCHEDULE_MINUTES
    next_offset = next((value for value in offsets if value > elapsed_minutes), None)
    if next_offset is None and offsets:
        repeat_minutes = settings.ARTICLE_SEARCH_REPEAT_MINUTES
        intervals = ((elapsed_minutes - offsets[-1]) // repeat_minutes) + 1
        next_offset = offsets[-1] + intervals * repeat_minutes
    candidate = started + timedelta(minutes=next_offset) if next_offset is not None else now + timedelta(hours=12)
    return min(candidate, article.monitor_until)


def _candidate_meets_retention_threshold(*, match: TitleMatch) -> bool:
    """Keep searchable candidates that meet the human-review threshold.

    Search providers do not consistently return a trustworthy publication time. The
    candidate list therefore uses title similarity alone: scores at or above the
    configured threshold are retained even when the result time is missing, equal to,
    or earlier than the original. Automatic repost confirmation remains governed by
    the separate, higher final-match threshold.
    """

    return match.similarity_score >= settings.SEARCH_CANDIDATE_MIN_SIMILARITY


@transaction.atomic
def upsert_global_repost(
    *,
    article: Article,
    candidate: SearchCandidate,
    match: TitleMatch,
    found_at: datetime,
    content_relation: str,
    owned_channel: OwnedChannel | None,
    classification_reason: str,
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
        "content_relation": content_relation,
        "owned_channel": owned_channel,
        "classification_reason": classification_reason,
        "classified_at": found_at,
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
            after_data={
                "article_id": article.id,
                "site_domain": domain,
                "similarity_score": match.similarity_score,
            },
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
    # A confirmed external repost is historical fact. A later automatic match
    # must not silently downgrade it; reclassification is an explicit command.
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


def _persist_search_candidate(
    *, run: SearchRun, canonical_url: str, candidate: SearchCandidate, phase: str
) -> SearchRunCandidate:
    """Persist a provider result immediately, before final matching is complete."""
    candidate_hash = sha256(canonical_url.encode("utf-8")).hexdigest()
    provider_code = candidate.provider.strip().lower()
    record = SearchRunCandidate.objects.filter(search_run=run, canonical_url_hash=candidate_hash).first()
    if record is None:
        record = SearchRunCandidate.objects.create(
            search_run=run,
            canonical_url_hash=candidate_hash,
            title=candidate.title[:500],
            site_name=candidate.site_name[:255],
            site_domain=candidate.domain[:253],
            raw_url=candidate.url,
            canonical_url=canonical_url,
            published_at=candidate.published_at,
            search_phases=[phase],
            provider_codes=[provider_code] if provider_code else [],
        )
    else:
        update_fields: list[str] = []
        if phase not in record.search_phases:
            record.search_phases = [*record.search_phases, phase]
            update_fields.append("search_phases")
        if provider_code and provider_code not in record.provider_codes:
            record.provider_codes = [*record.provider_codes, provider_code]
            update_fields.append("provider_codes")
        if update_fields:
            record.save(update_fields=update_fields)
    return record


def _metadata_values(candidate: SearchCandidate, key: str) -> set[str]:
    values: set[str] = set()
    raw_value = candidate.raw_data.get(key)
    if isinstance(raw_value, str) and raw_value.strip():
        values.add(raw_value.strip().casefold())
    elif isinstance(raw_value, list):
        values.update(str(item).strip().casefold() for item in raw_value if str(item).strip())
    return values


def _rule_values(rules: dict[str, object], key: str) -> set[str]:
    value = rules.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {str(item).strip().casefold() for item in value if str(item).strip()}


def _host_matches(host: str, patterns: set[str], *, exact: bool = False) -> bool:
    return any(host == pattern or (not exact and host.endswith(f".{pattern}")) for pattern in patterns)


def classify_owned_channel(
    candidate: SearchCandidate, *, channels: list[OwnedChannel] | None = None
) -> tuple[str, OwnedChannel | None, str]:
    """Classify title-matched results using configurable, conjunctive channel rules.

    A channel rule can declare broad platform domains plus stronger account/path/metadata
    checks. A broad platform indication without the stronger checks stays reviewable.
    """

    host = (candidate.domain or urlsplit(candidate.url).hostname or "").casefold().rstrip(".")
    path = urlsplit(candidate.url).path.casefold()
    candidates = channels if channels is not None else list(OwnedChannel.objects.filter(is_active=True))
    review_result: tuple[str, OwnedChannel, str] | None = None
    for channel in candidates:
        rules = channel.match_rules if isinstance(channel.match_rules, dict) else {}
        domains = _rule_values(rules, "domains")
        subdomains = _rule_values(rules, "subdomains")
        platform_domains = _rule_values(rules, "platform_domains")
        domain_related = _host_matches(host, domains) or _host_matches(host, subdomains, exact=True)
        platform_related = domain_related or _host_matches(host, platform_domains)
        if not platform_related:
            continue

        path_prefixes = _rule_values(rules, "path_prefixes")
        account_ids = _rule_values(rules, "account_ids")
        account_names = _rule_values(rules, "account_names")
        author_names = _rule_values(rules, "author_names")
        site_names = _rule_values(rules, "site_names")
        metadata_rules = rules.get("provider_metadata", {})
        strong_rule_configured = bool(
            path_prefixes or account_ids or account_names or author_names or site_names or metadata_rules
        )
        if path_prefixes and not any(path.startswith(prefix) for prefix in path_prefixes):
            review_result = review_result or ("REVIEW_REQUIRED", channel, "OWNED_CHANNEL_PATH_UNCONFIRMED")
            continue
        if account_ids and not (_metadata_values(candidate, "account_id") & account_ids):
            review_result = review_result or (
                "REVIEW_REQUIRED",
                channel,
                "OWNED_CHANNEL_ACCOUNT_ID_UNCONFIRMED",
            )
            continue
        account_metadata = _metadata_values(candidate, "account_name") | _metadata_values(candidate, "author")
        if account_names and not (account_metadata & account_names):
            review_result = review_result or (
                "REVIEW_REQUIRED",
                channel,
                "OWNED_CHANNEL_ACCOUNT_NAME_UNCONFIRMED",
            )
            continue
        if author_names and not (_metadata_values(candidate, "author") & author_names):
            review_result = review_result or (
                "REVIEW_REQUIRED",
                channel,
                "OWNED_CHANNEL_AUTHOR_UNCONFIRMED",
            )
            continue
        if site_names and candidate.site_name.strip().casefold() not in site_names:
            review_result = review_result or (
                "REVIEW_REQUIRED",
                channel,
                "OWNED_CHANNEL_SITE_NAME_UNCONFIRMED",
            )
            continue
        if isinstance(metadata_rules, dict):
            for key, expected in metadata_rules.items():
                expected_values = (
                    {str(item).casefold() for item in expected}
                    if isinstance(expected, list)
                    else {str(expected).casefold()}
                )
                if not (_metadata_values(candidate, str(key)) & expected_values):
                    review_result = review_result or (
                        "REVIEW_REQUIRED",
                        channel,
                        "OWNED_CHANNEL_METADATA_UNCONFIRMED",
                    )
                    break
            else:
                if domain_related and not strong_rule_configured:
                    return "OWNED", channel, "OWNED_CHANNEL_DOMAIN_MATCH"
                if platform_related and strong_rule_configured:
                    return "OWNED", channel, "OWNED_CHANNEL_CONFIGURED_RULE_MATCH"
        elif domain_related and not strong_rule_configured:
            return "OWNED", channel, "OWNED_CHANNEL_DOMAIN_MATCH"
        elif platform_related and strong_rule_configured:
            return "OWNED", channel, "OWNED_CHANNEL_CONFIGURED_RULE_MATCH"
    return review_result or ("REPOST", None, "EXTERNAL_SITE")


def _classify_search_candidate(
    record: SearchRunCandidate,
    *,
    disposition: SearchCandidateDisposition,
    reason_code: str,
    similarity_score: Decimal | float | None = None,
    content_relation: str = "",
    owned_channel: OwnedChannel | None = None,
) -> None:
    record.disposition = disposition
    record.reason_code = reason_code
    record.similarity_score = similarity_score
    record.content_relation = content_relation
    record.owned_channel = owned_channel
    record.classification_reason = reason_code
    record.classified_at = timezone.now() if content_relation else None
    record.save(
        update_fields=[
            "disposition",
            "reason_code",
            "similarity_score",
            "content_relation",
            "owned_channel",
            "classification_reason",
            "classified_at",
        ]
    )


def _candidate_as_search_candidate(record: SearchRunCandidate) -> SearchCandidate:
    return SearchCandidate(
        title=record.title,
        url=record.canonical_url,
        domain=record.site_domain,
        published_at=record.published_at,
        provider=record.search_run.provider,
        site_name=record.site_name,
    )


def _refresh_search_run_counts(run: SearchRun) -> None:
    candidates = SearchRunCandidate.objects.filter(search_run=run)
    phases = candidates.values_list("search_phases", flat=True)
    run.candidate_count = candidates.count()
    run.exact_candidate_count = sum(1 for value in phases if "EXACT" in value)
    # Re-evaluate because the query set is lazy and `phases` has already been
    # consumed above. This is portable across MySQL JSON implementations.
    run.broad_candidate_count = sum(
        1 for value in candidates.values_list("search_phases", flat=True) if "BROAD" in value
    )
    run.merged_candidate_count = run.candidate_count
    run.matched_count = candidates.filter(disposition=SearchCandidateDisposition.MATCHED).count()
    run.repost_count = candidates.filter(content_relation=ContentRelation.REPOST).count()
    run.owned_count = candidates.filter(content_relation=ContentRelation.OWNED).count()
    run.review_required_count = candidates.filter(content_relation=ContentRelation.REVIEW_REQUIRED).count()
    run.save(
        update_fields=[
            "candidate_count",
            "exact_candidate_count",
            "broad_candidate_count",
            "merged_candidate_count",
            "matched_count",
            "repost_count",
            "owned_count",
            "review_required_count",
        ]
    )


def _release_expired_targeted_crawl_claims(*, source: Source, now: datetime) -> None:
    """Return abandoned browser leases to the source-specific queue."""

    TargetedCrawlTask.objects.filter(
        source=source,
        status=TargetedCrawlTaskStatus.CLAIMED,
        claim_expires_at__lte=now,
    ).update(
        status=TargetedCrawlTaskStatus.PENDING,
        claimed_by_token=None,
        claim_token_hash="",
        claimed_at=None,
        claim_expires_at=None,
    )


@transaction.atomic
def due_targeted_crawl_tasks(*, source: Source, limit: int) -> list[TargetedCrawlTask]:
    """Materialize due browser-worker tasks only for the token's source.

    A task is durable per source article and each completed claim produces a separate
    SearchRun.  That preserves browser execution history without queueing seven days
    of ETA work or exposing other sources' original titles.
    """

    now = timezone.now()
    _release_expired_targeted_crawl_claims(source=source, now=now)
    articles = list(
        Article.objects.select_for_update()
        .filter(
            source=source,
            status="ACTIVE",
            monitoring_status=ArticleMonitoringStatus.ACTIVE,
            monitor_until__gt=now,
        )
        .only("id", "title", "monitor_started_at", "monitor_until")
    )
    for article in articles:
        task, created = TargetedCrawlTask.objects.get_or_create(
            article=article,
            defaults={
                "source": source,
                "query": article.title,
                "next_available_at": now,
            },
        )
        if not created and task.status == TargetedCrawlTaskStatus.PENDING and task.query != article.title:
            task.query = article.title
            task.next_available_at = now
            task.save(update_fields=["query", "next_available_at", "updated_at"])
    return list(
        TargetedCrawlTask.objects.select_related("article")
        .filter(
            source=source,
            status=TargetedCrawlTaskStatus.PENDING,
            next_available_at__lte=now,
        )
        .order_by("next_available_at", "id")[:limit]
    )


@transaction.atomic
def claim_targeted_crawl_task(*, task_id: int, token: SourceIngestToken) -> tuple[TargetedCrawlTask, SearchRun, str]:
    now = timezone.now()
    task = (
        TargetedCrawlTask.objects.select_for_update()
        .select_related("article")
        .filter(pk=task_id, source=token.source)
        .first()
    )
    if task is None:
        raise PermissionError("任务不存在或不属于当前来源。")
    if task.status == TargetedCrawlTaskStatus.CLAIMED and task.claim_expires_at and task.claim_expires_at <= now:
        task.status = TargetedCrawlTaskStatus.PENDING
        task.claimed_by_token = None
        task.claim_token_hash = ""
        task.claimed_at = None
        task.claim_expires_at = None
    if task.status != TargetedCrawlTaskStatus.PENDING:
        raise ValueError("任务已被其他采集端领取或已关闭。")
    if task.next_available_at and task.next_available_at > now:
        raise ValueError("任务尚未到执行时间。")

    claim_token = secrets.token_urlsafe(32)
    run = SearchRun.objects.create(
        article=task.article,
        provider="targeted_crawl",
        query=json.dumps([f'"{task.query}"', task.query], ensure_ascii=False),
        status=SearchRunStatus.RUNNING,
        started_at=now,
    )
    task.status = TargetedCrawlTaskStatus.CLAIMED
    task.claimed_by_token = token
    task.claim_token_hash = sha256(claim_token.encode("utf-8")).hexdigest()
    task.claimed_at = now
    task.claim_expires_at = now + timedelta(seconds=settings.TARGETED_CRAWL_CLAIM_TTL_SECONDS)
    task.last_run = run
    task.attempt_count += 1
    task.last_error_code = ""
    task.last_error_message = ""
    task.save(
        update_fields=[
            "status",
            "claimed_by_token",
            "claim_token_hash",
            "claimed_at",
            "claim_expires_at",
            "last_run",
            "attempt_count",
            "last_error_code",
            "last_error_message",
            "updated_at",
        ]
    )
    return task, run, claim_token


def _locked_targeted_crawl_run(
    *, task_id: int, run_id: int, claim_token: str, token: SourceIngestToken
) -> tuple[TargetedCrawlTask, SearchRun]:
    task = (
        TargetedCrawlTask.objects.select_for_update()
        .select_related("article")
        .filter(pk=task_id, source=token.source, claimed_by_token=token)
        .first()
    )
    if task is None:
        raise PermissionError("任务不存在、不属于当前来源，或不属于当前采集端。")
    expected_hash = sha256(claim_token.encode("utf-8")).hexdigest()
    if (
        task.status != TargetedCrawlTaskStatus.CLAIMED
        or not task.claim_expires_at
        or task.claim_expires_at <= timezone.now()
        or not task.claim_token_hash
        or not hmac.compare_digest(task.claim_token_hash, expected_hash)
    ):
        raise PermissionError("任务租约无效或已过期。")
    run = SearchRun.objects.select_for_update().filter(pk=run_id, article=task.article).first()
    if run is None or task.last_run_id != run.id or run.status != SearchRunStatus.RUNNING:
        raise ValueError("运行记录不存在或已经结束。")
    return task, run


def _classify_targeted_crawl_candidate(
    *, task: TargetedCrawlTask, run: SearchRun, candidate: SearchCandidate, phase: str
) -> tuple[SearchRunCandidate | None, bool]:
    article = task.article
    match = compare_titles(article.title, candidate)
    if not _candidate_meets_retention_threshold(match=match):
        return None, False

    canonical_url = canonicalize_http_url(candidate.url)
    if is_url_for_source(task.source, canonical_url):
        return None, False
    if article.original_url and canonical_url == canonicalize_http_url(article.original_url):
        return None, False

    record = _persist_search_candidate(run=run, canonical_url=canonical_url, candidate=candidate, phase=phase)
    if not match.matched:
        _classify_search_candidate(
            record,
            disposition=SearchCandidateDisposition.NOT_MATCHED,
            similarity_score=match.similarity_score,
            reason_code="TITLE_NOT_MATCHED",
        )
        return record, False

    relation, owned_channel, reason = classify_owned_channel(candidate)
    _classify_search_candidate(
        record,
        disposition=SearchCandidateDisposition.MATCHED,
        similarity_score=match.similarity_score,
        reason_code=reason,
        content_relation=relation,
        owned_channel=owned_channel,
    )
    _, created = upsert_global_repost(
        article=article,
        candidate=candidate,
        match=match,
        found_at=timezone.now(),
        content_relation=relation,
        owned_channel=owned_channel,
        classification_reason=reason,
    )
    return record, bool(created and relation == ContentRelation.REPOST)


@transaction.atomic
def submit_targeted_crawl_candidates(
    *,
    task_id: int,
    run_id: int,
    claim_token: str,
    token: SourceIngestToken,
    items: list[dict[str, object]],
) -> list[SearchRunCandidate]:
    task, run = _locked_targeted_crawl_run(
        task_id=task_id,
        run_id=run_id,
        claim_token=claim_token,
        token=token,
    )
    persisted: list[SearchRunCandidate] = []
    new_repost_count = 0
    for item in items:
        raw_url = str(item["url"])
        canonical_url = canonicalize_http_url(raw_url)
        candidate = SearchCandidate(
            title=str(item["title"]),
            url=raw_url,
            domain=(urlsplit(canonical_url).hostname or "").lower(),
            site_name=str(item.get("site_name", "")),
            published_at=cast(datetime | None, item.get("published_at")),
            provider=str(item.get("provider_code", "targeted_crawl")),
        )
        record, created = _classify_targeted_crawl_candidate(
            task=task,
            run=run,
            candidate=candidate,
            phase=str(item.get("search_phase", "EXACT")),
        )
        if record is not None:
            persisted.append(record)
        new_repost_count += int(created)
    if new_repost_count:
        run.new_repost_count += new_repost_count
        run.save(update_fields=["new_repost_count"])
    _refresh_search_run_counts(run)
    return persisted


@transaction.atomic
def complete_targeted_crawl_run(
    *,
    task_id: int,
    run_id: int,
    claim_token: str,
    token: SourceIngestToken,
    run_status: str,
    error_code: str = "",
    error_message: str = "",
) -> tuple[TargetedCrawlTask, SearchRun]:
    task, run = _locked_targeted_crawl_run(
        task_id=task_id,
        run_id=run_id,
        claim_token=claim_token,
        token=token,
    )
    now = timezone.now()
    _refresh_search_run_counts(run)
    run.status = SearchRunStatus.SUCCESS if run_status == "SUCCESS" else SearchRunStatus.ERROR
    run.error_code = error_code if run_status == "ERROR" else ""
    run.error_message = safe_error_message(error_message) if run_status == "ERROR" else ""
    run.completed_at = now
    run.save(update_fields=["status", "error_code", "error_message", "completed_at"])

    task.status = TargetedCrawlTaskStatus.PENDING
    task.claimed_by_token = None
    task.claim_token_hash = ""
    task.claimed_at = None
    task.claim_expires_at = None
    task.last_completed_at = now
    task.last_error_code = run.error_code
    task.last_error_message = run.error_message
    if run_status == "SUCCESS":
        task.next_available_at = _next_search_time(task.article, now)
    else:
        task.next_available_at = min(
            now + timedelta(minutes=settings.SEARCH_ERROR_BACKOFF_MINUTES),
            task.article.monitor_until or now,
        )
    if task.next_available_at is None:
        task.status = TargetedCrawlTaskStatus.CLOSED
    task.save(
        update_fields=[
            "status",
            "claimed_by_token",
            "claim_token_hash",
            "claimed_at",
            "claim_expires_at",
            "last_completed_at",
            "last_error_code",
            "last_error_message",
            "next_available_at",
            "updated_at",
        ]
    )
    return task, run


@transaction.atomic
def review_search_candidate(
    *,
    candidate_id: int,
    action: str,
    reason: str,
    owned_channel_id: int | None = None,
) -> tuple[SearchRunCandidate, RepostRecord | None]:
    """Apply a traceable human decision to one retained search candidate.

    Only confirmed external reposts participate in the repost workspace/export.
    Confirmed owned distribution stays in the reading-monitor boundary instead.
    """

    candidate = (
        SearchRunCandidate.objects.select_for_update().select_related("search_run__article").get(pk=candidate_id)
    )
    article = candidate.search_run.article
    reason_text = f"MANUAL_REVIEW: {reason.strip()}"[:500]
    existing = (
        RepostRecord.objects.select_for_update()
        .filter(
            article=article,
            canonical_url_hash=candidate.canonical_url_hash,
        )
        .first()
    )
    record: RepostRecord | None = None

    if action == "EXCLUDE":
        if existing and existing.content_relation == ContentRelation.REPOST and existing.is_valid:
            raise ValueError("已确认的外部转载不能通过候选复核排除，请使用专用作废流程。")
        candidate.disposition = SearchCandidateDisposition.EXCLUDED_MANUAL
        candidate.reason_code = "MANUAL_EXCLUDED"
        candidate.content_relation = ""
        candidate.owned_channel = None
        candidate.classification_reason = reason_text
        candidate.classified_at = timezone.now()
        candidate.save(
            update_fields=[
                "disposition",
                "reason_code",
                "content_relation",
                "owned_channel",
                "classification_reason",
                "classified_at",
            ]
        )
        if existing:
            existing.is_valid = False
            existing.invalidation_reason = reason_text
            existing.invalidated_at = timezone.now()
            existing.save(update_fields=["is_valid", "invalidation_reason", "invalidated_at", "updated_at"])
    else:
        owned_channel: OwnedChannel | None = None
        relation = ContentRelation.REPOST
        if action == "CONFIRM_OWNED":
            if not owned_channel_id:
                raise ValueError("归入阅读量时必须选择自有渠道。")
            owned_channel = OwnedChannel.objects.filter(pk=owned_channel_id, is_active=True).first()
            if owned_channel is None:
                raise ValueError("指定的自有渠道不存在或已停用。")
            relation = ContentRelation.OWNED
            if (
                existing
                and existing.content_relation == ContentRelation.REPOST
                and existing.is_valid
                and candidate.reason_code != "MANUAL_REPOST"
            ):
                raise ValueError("系统确认的外部转载不能通过候选复核改为自有分发。")
        elif action != "CONFIRM_REPOST":
            raise ValueError("不支持的候选复核动作。")

        source_candidate = _candidate_as_search_candidate(candidate)
        match = compare_titles(article.title, source_candidate)
        record, created = upsert_global_repost(
            article=article,
            candidate=source_candidate,
            match=match,
            found_at=timezone.now(),
            content_relation=relation,
            owned_channel=owned_channel,
            classification_reason=reason_text,
        )
        record.content_relation = relation
        record.owned_channel = owned_channel
        record.classification_reason = reason_text
        record.classified_at = timezone.now()
        record.is_valid = True
        record.save(
            update_fields=[
                "content_relation",
                "owned_channel",
                "classification_reason",
                "classified_at",
                "is_valid",
                "updated_at",
            ]
        )
        candidate.disposition = SearchCandidateDisposition.MATCHED
        candidate.reason_code = f"MANUAL_{relation}"
        candidate.content_relation = relation
        candidate.owned_channel = owned_channel
        candidate.classification_reason = reason_text
        candidate.classified_at = timezone.now()
        candidate.similarity_score = Decimal(str(round(match.similarity_score, 2)))
        candidate.save(
            update_fields=[
                "disposition",
                "reason_code",
                "content_relation",
                "owned_channel",
                "classification_reason",
                "classified_at",
                "similarity_score",
            ]
        )
        if relation == ContentRelation.REPOST and created:
            candidate.search_run.new_repost_count += 1
            candidate.search_run.save(update_fields=["new_repost_count"])

    _refresh_search_run_counts(candidate.search_run)
    return candidate, record


def _enabled_provider_instances() -> list[tuple[str, SearchProvider]]:
    """Resolve enabled database providers in priority order without exposing keys."""

    configurations = list(SearchProviderConfiguration.objects.filter(enabled=True).order_by("priority", "code"))
    if not configurations:
        provider = configured_search_provider()
        return [(provider.code, provider)]
    providers: list[tuple[str, SearchProvider]] = []
    for configuration in configurations:
        try:
            providers.append((configuration.code, search_provider_for_code(configuration.code)))
        except SearchProviderError as error:
            _mark_provider_failure(configuration, error)
    if not providers:
        raise SearchProviderError("没有可用的已启用搜索来源。")
    return providers


def _mark_provider_success(configuration: SearchProviderConfiguration) -> None:
    configuration.last_success_at = timezone.now()
    configuration.consecutive_failures = 0
    configuration.last_failure_code = ""
    configuration.last_failure_message = ""
    configuration.save(
        update_fields=[
            "last_success_at",
            "consecutive_failures",
            "last_failure_code",
            "last_failure_message",
            "updated_at",
        ]
    )


def _mark_provider_failure(configuration: SearchProviderConfiguration, error: SearchProviderError) -> None:
    configuration.last_failure_at = timezone.now()
    configuration.consecutive_failures += 1
    configuration.last_failure_code = error.code
    configuration.last_failure_message = safe_error_message(error)
    configuration.save(
        update_fields=[
            "last_failure_at",
            "consecutive_failures",
            "last_failure_code",
            "last_failure_message",
            "updated_at",
        ]
    )


def _configured_provider_row(provider_code: str) -> SearchProviderConfiguration | None:
    return SearchProviderConfiguration.objects.filter(code=provider_code, enabled=True).first()


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
        providers = (
            [(provider_instance.code, provider_instance)]
            if provider_instance is not None
            else _enabled_provider_instances()
        )
        provider_code = ",".join(configured_code for configured_code, _ in providers)
        all_candidates: dict[str, SearchCandidate] = {}
        stage_errors: list[SearchProviderError] = []
        stage_counts: dict[str, int] = {"EXACT": 0, "BROAD": 0}
        successful_provider_calls = 0
        for configured_code, selected_provider in providers:
            configuration = _configured_provider_row(configured_code)
            provider_had_success = False
            for phase, query in (("EXACT", queries[0]), ("BROAD", queries[1])):
                try:
                    candidates = selected_provider.search(
                        query,
                        freshness_from=article.published_at,
                        freshness_to=article.monitor_until,
                        limit=settings.SEARCH_RESULT_LIMIT,
                    )
                except SearchProviderError as error:
                    stage_errors.append(error)
                    # Test-injected and legacy single providers retain the two-stage contract:
                    # an exact query failure must not suppress its broad query. For configured
                    # multi-source searches, continue with the next source to limit a failed
                    # provider's impact on the full scheduled run.
                    if provider_instance is None:
                        break
                    continue
                provider_had_success = True
                successful_provider_calls += 1
                for candidate in candidates:
                    if not candidate.provider:
                        candidate = SearchCandidate(
                            title=candidate.title,
                            url=candidate.url,
                            snippet=candidate.snippet,
                            display_url=candidate.display_url,
                            domain=candidate.domain,
                            published_at=candidate.published_at,
                            provider=configured_code,
                            site_name=candidate.site_name,
                            raw_data=candidate.raw_data,
                        )
                    match = compare_titles(article.title, candidate)
                    if not _candidate_meets_retention_threshold(match=match):
                        continue
                    try:
                        canonical = canonicalize_http_url(candidate.url)
                    except ValueError:
                        continue
                    if article.original_url and canonical == canonicalize_http_url(article.original_url):
                        continue
                    if canonical not in all_candidates:
                        all_candidates[canonical] = candidate
                    _persist_search_candidate(run=run, canonical_url=canonical, candidate=candidate, phase=phase)
                    stage_counts[phase] += 1

                # Persist each provider response so URLs remain visible while the next source runs.
                run.candidate_count = len(all_candidates)
                run.exact_candidate_count = stage_counts["EXACT"]
                run.broad_candidate_count = stage_counts["BROAD"]
                run.merged_candidate_count = len(all_candidates)
                run.save(
                    update_fields=[
                        "candidate_count",
                        "exact_candidate_count",
                        "broad_candidate_count",
                        "merged_candidate_count",
                    ]
                )
            if configuration is not None:
                if provider_had_success:
                    _mark_provider_success(configuration)
                elif stage_errors:
                    _mark_provider_failure(configuration, stage_errors[-1])

        if successful_provider_calls == 0:
            raise stage_errors[-1]

        matched_count = 0
        new_count = 0
        owned_count = 0
        repost_count = 0
        review_count = 0
        owned_channels = list(OwnedChannel.objects.filter(is_active=True))
        for canonical, candidate in all_candidates.items():
            candidate_record = SearchRunCandidate.objects.get(
                search_run=run,
                canonical_url_hash=sha256(canonical.encode("utf-8")).hexdigest(),
            )
            match = compare_titles(article.title, candidate)
            _classify_search_candidate(
                candidate_record,
                disposition=(
                    SearchCandidateDisposition.MATCHED if match.matched else SearchCandidateDisposition.NOT_MATCHED
                ),
                similarity_score=match.similarity_score,
                reason_code="TITLE_MATCH" if match.matched else "TITLE_NOT_MATCHED",
            )
            if not match.matched:
                continue
            matched_count += 1
            relation, owned_channel, classification_reason = classify_owned_channel(candidate, channels=owned_channels)
            _classify_search_candidate(
                candidate_record,
                disposition=SearchCandidateDisposition.MATCHED,
                reason_code=classification_reason,
                similarity_score=match.similarity_score,
                content_relation=relation,
                owned_channel=owned_channel,
            )
            _, created = upsert_global_repost(
                article=article,
                candidate=candidate,
                match=match,
                found_at=now,
                content_relation=relation,
                owned_channel=owned_channel,
                classification_reason=classification_reason,
            )
            if relation == ContentRelation.REPOST:
                repost_count += 1
                new_count += int(created)
            elif relation == ContentRelation.OWNED:
                owned_count += 1
            else:
                review_count += 1
        run.provider = provider_code
        run.status = SearchRunStatus.SUCCESS
        run.candidate_count = len(all_candidates)
        run.exact_candidate_count = stage_counts["EXACT"]
        run.broad_candidate_count = stage_counts["BROAD"]
        run.merged_candidate_count = len(all_candidates)
        run.matched_count = matched_count
        run.owned_count = owned_count
        run.repost_count = repost_count
        run.review_required_count = review_count
        run.new_repost_count = new_count
        run.completed_at = timezone.now()
        if stage_errors:
            run.error_code = "PARTIAL_STAGE_FAILURE"
            run.error_message = "; ".join(f"{error.code}: {safe_error_message(error)}" for error in stage_errors)[:500]
        run.save()
        article.last_searched_at = run.completed_at
        article.next_search_at = _next_search_time(article, run.completed_at)
        if article.next_search_at is None:
            article.monitoring_status = ArticleMonitoringStatus.COMPLETED
        article.save(
            update_fields=[
                "last_searched_at",
                "next_search_at",
                "monitoring_status",
                "updated_at",
            ]
        )
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
    record.save(
        update_fields=[
            "availability_status",
            "last_availability_checked_at",
            "updated_at",
        ]
    )
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
            # Candidate links belong to their search run and are retained with the
            # article for its full one-year retention period. The cascade only runs
            # when the article itself is eligible for permanent deletion.
            SearchRun.objects.filter(article_id=article_id).delete()
            Article.objects.filter(id=article_id, retention_until__lt=now).delete()
            details["articles_deleted"] += 1
    return details
