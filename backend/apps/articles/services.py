import html
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any, Final, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role, User

from .models import Article

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
        column in message
        for column in ("normalized_title", "published_date", "duplicate_slot")
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


def create_standard_article(*, data: Mapping[str, Any], created_by: User) -> Article:
    values = _article_values(data)
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
            raise ArticleDuplicateError(
                "同日存在相同标准化标题，需管理员确认后创建独立文章。"
            ) from error
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
    normalized_title = cast(str, values["normalized_title"])
    published_date = cast(date, values["published_date"])

    for _attempt in range(max_retries):
        try:
            with transaction.atomic():
                existing = list(
                    Article.objects.select_for_update()
                    .filter(
                        normalized_title=normalized_title, published_date=published_date
                    )
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
