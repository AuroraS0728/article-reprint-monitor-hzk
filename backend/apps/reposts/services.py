from __future__ import annotations

from hashlib import sha256

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.articles.models import Article
from apps.monitoring.services import normalize_repost_url
from apps.platforms.models import Platform

from .models import RepostRecord


class ManualSupplementConflict(ValueError):
    pass


@transaction.atomic
def create_manual_supplement(
    *, article: Article, platform: Platform, repost_url: str, reason: str, actor: User
) -> RepostRecord:
    normalized_url = normalize_repost_url(repost_url)
    normalized_url_hash = sha256(normalized_url.encode()).hexdigest()
    if RepostRecord.objects.filter(
        article=article, platform=platform, normalized_url_hash=normalized_url_hash
    ).exists():
        raise ManualSupplementConflict("该文章、平台和转载链接的记录已存在，不能重复补录。")
    now = timezone.now()
    try:
        return RepostRecord.objects.create(
            article=article,
            platform=platform,
            original_url=repost_url,
            normalized_url=normalized_url,
            normalized_url_hash=normalized_url_hash,
            final_url=repost_url,
            repost_title=article.title,
            first_discovered_at=now,
            last_checked_at=now,
            data_source="MANUAL_SUPPLEMENT",
            manual_reason=reason,
            manually_added_by=actor,
            manually_added_at=now,
        )
    except IntegrityError as error:
        raise ManualSupplementConflict("该转载链接已被并发创建，请刷新后查看。") from error


def manual_repost_before_data(record: RepostRecord) -> dict[str, object]:
    return {
        "article_id": record.article_id,
        "platform_id": record.platform_id,
        "normalized_url": record.normalized_url,
        "data_source": record.data_source,
        "manual_reason": record.manual_reason,
        "is_valid": record.is_valid,
        "invalidated_at": record.invalidated_at.isoformat() if record.invalidated_at else None,
        "invalidation_reason": record.invalidation_reason,
    }


@transaction.atomic
def set_manual_supplement_validity(*, record: RepostRecord, valid: bool, reason: str, actor: User) -> RepostRecord:
    if not record.is_manual_supplement:
        raise ValueError("仅人工补录记录可以作废或恢复。")
    if record.is_valid == valid:
        raise ValueError("人工补录已处于目标状态。")
    record.is_valid = valid
    if valid:
        record.invalidated_by = None
        record.invalidated_at = None
        record.invalidation_reason = ""
    else:
        if not reason.strip():
            raise ValueError("作废人工补录必须填写原因。")
        record.invalidated_by = actor
        record.invalidated_at = timezone.now()
        record.invalidation_reason = reason.strip()
    record.save(
        update_fields=[
            "is_valid",
            "invalidated_by",
            "invalidated_at",
            "invalidation_reason",
            "updated_at",
        ]
    )
    return record
