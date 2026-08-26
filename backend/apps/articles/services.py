import html
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Any, Final, cast

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role, User

from .models import Article, ArticleMonitoringStatus

TITLE_TRANSLATION: Final[dict[str, str | int | None]] = {
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "，": ",",
    "：": ":",
}


def normalize_title(value: str, confirmed_suffixes: Iterable[str] = ()) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.translate(str.maketrans(TITLE_TRANSLATION))
    for suffix in confirmed_suffixes:
        suffix_value = suffix.strip()
        if not suffix_value:
            continue
        for marker in (
            suffix_value,
            f" - {suffix_value}",
            f" _ {suffix_value}",
            f"_{suffix_value}",
            f"（{suffix_value}）",
            f"({suffix_value})",
        ):
            if normalized.endswith(marker):
                normalized = normalized[: -len(marker)].rstrip(" _-*")
                break
    return normalized


class ArticleDuplicateError(ValueError):
    code = "DUPLICATE_ARTICLE"


def is_title_slot_conflict(error: IntegrityError) -> bool:
    message = str(error).lower()
    return "uniq_article_title_date_slot" in message or all(
        column in message for column in ("normalized_title", "published_date", "duplicate_slot")
    )


def _article_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(data)
    values.pop("duplicate_slot", None)
    values.pop("duplicate_approved_by", None)
    values.pop("duplicate_approved_at", None)
    values.pop("duplicate_reason", None)
    values.pop("created_by", None)
    values["title"] = str(values["title"]).strip()
    values["normalized_title"] = normalize_title(values["title"])
    if not isinstance(values.get("published_date"), date):
        raise ValueError("原创发布日期无效。")
    return values


def _single_active_source() -> Any | None:
    """Return the configured source for operator-created articles when unambiguous.

    Source-token workers are intentionally scoped to a Source.  Articles entered
    in the admin UI do not carry a token, so when the installation has exactly
    one active source we bind them to it.  With multiple active sources an
    administrator must use the source ingestion path instead of silently
    assigning an article to the wrong tenant.
    """

    from apps.sources.models import Source

    token_sources = list(
        Source.objects.filter(is_active=True, ingest_tokens__is_active=True).distinct().order_by("id")[:2]
    )
    if len(token_sources) == 1:
        return token_sources[0]
    sources = list(Source.objects.filter(is_active=True).order_by("id")[:2])
    return sources[0] if len(sources) == 1 else None


def _initialize_manual_monitoring(values: dict[str, Any]) -> None:
    """Initialize the same seven-day lifecycle used by source ingestion."""

    now = timezone.now()
    published_date = cast(date, values["published_date"])
    published_at = values.get("published_at")
    if not isinstance(published_at, datetime):
        local_tz = timezone.get_current_timezone()
        published_at = timezone.make_aware(datetime.combine(published_date, time.min), local_tz)
        values["published_at"] = published_at
    if timezone.is_naive(published_at):
        values["published_at"] = timezone.make_aware(published_at, timezone.get_current_timezone())
        published_at = values["published_at"]

    monitor_until = published_at + timedelta(days=settings.ARTICLE_MONITOR_DAYS)
    retention_until = published_at + timedelta(days=settings.ARTICLE_RETENTION_DAYS)
    values.setdefault("discovered_at", now)
    values.setdefault("monitor_started_at", now if now < monitor_until else None)
    values.setdefault("monitor_until", monitor_until)
    values.setdefault("retention_until", retention_until)
    values.setdefault(
        "monitoring_status",
        ArticleMonitoringStatus.ACTIVE if now < monitor_until else ArticleMonitoringStatus.COMPLETED,
    )
    values.setdefault("next_search_at", now if now < monitor_until else None)
    values.setdefault("source", _single_active_source())


def initialize_existing_manual_article_monitoring(article: Article, *, source: Any) -> bool:
    """Attach an older hand-entered article to its browser-worker source.

    Earlier versions saved manual and Excel articles without the source-scoped
    monitoring lifecycle.  A source worker calls this only for unbound active
    articles, so an existing source-ingested article is never reassigned.
    """

    if article.source_id is not None:
        return False
    values: dict[str, Any] = {"published_date": article.published_date, "source": source}
    if article.published_at is not None:
        values["published_at"] = article.published_at
    _initialize_manual_monitoring(values)

    fields = (
        "source",
        "published_at",
        "discovered_at",
        "monitor_started_at",
        "monitor_until",
        "retention_until",
        "monitoring_status",
        "next_search_at",
    )
    update_fields = [field for field in fields if getattr(article, field) != values[field]]
    if not update_fields:
        return False
    for field in update_fields:
        setattr(article, field, values[field])
    article.save(update_fields=[*update_fields, "updated_at"])
    return True


def create_standard_article(*, data: Mapping[str, Any], created_by: User) -> Article:
    values = _article_values(data)
    _initialize_manual_monitoring(values)
    values.update(
        {
            "duplicate_slot": 0,
            "duplicate_approved_by": None,
            "duplicate_approved_at": None,
            "duplicate_reason": "",
            "created_by": created_by,
        }
    )
    try:
        with transaction.atomic():
            return Article.objects.create(**cast(dict[str, Any], values))
    except IntegrityError as error:
        if is_title_slot_conflict(error):
            raise ArticleDuplicateError("同日存在相同标准化标题，需管理员确认后创建独立文章。") from error
        raise


def create_approved_duplicate(
    *,
    data: Mapping[str, Any],
    approved_by: User,
    duplicate_reason: str,
    max_retries: int = 3,
) -> Article:
    reason = duplicate_reason.strip()
    if not reason:
        raise ValueError("管理员确认重复时必须填写原因。")
    if not (approved_by.is_superuser or approved_by.role == Role.ADMIN):
        raise PermissionError("只有管理员可以批准重复文章。")
    values = _article_values(data)
    _initialize_manual_monitoring(values)
    normalized_title = cast(str, values["normalized_title"])
    published_date = cast(date, values["published_date"])

    for _attempt in range(max_retries):
        try:
            with transaction.atomic():
                existing = list(
                    Article.objects.select_for_update()
                    .filter(normalized_title=normalized_title, published_date=published_date)
                    .order_by("duplicate_slot", "id")
                )
                if not existing:
                    raise ArticleDuplicateError("没有可供管理员确认的重复文章组。")
                next_slot = max(article.duplicate_slot for article in existing) + 1
                approved_values = {
                    **values,
                    "duplicate_slot": next_slot,
                    "duplicate_approved_by": approved_by,
                    "duplicate_approved_at": timezone.now(),
                    "duplicate_reason": reason,
                    "created_by": approved_by,
                }
                return Article.objects.create(**cast(dict[str, Any], approved_values))
        except IntegrityError as error:
            if not is_title_slot_conflict(error):
                raise
    raise ArticleDuplicateError("管理员并发批准重复文章发生冲突，请重试。")
