from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date
from typing import cast

from django.db import transaction

from apps.articles.models import Article, ArticleStatus
from apps.platforms.models import Platform, PlatformStatus

from .models import DetectionBatch, DetectionResult


def create_batch(
    *,
    trigger: str,
    article_ids: Iterable[int] = (),
    platform_ids: Iterable[int] = (),
    article_date_from: date | None = None,
    article_date_to: date | None = None,
    use_all_enabled_platforms: bool = False,
    created_by: object | None = None,
    idempotency_key: str,
) -> DetectionBatch:
    selected_articles = Article.objects.filter(status=ArticleStatus.ACTIVE)
    if article_ids:
        selected_articles = selected_articles.filter(id__in=set(article_ids))
    if article_date_from:
        selected_articles = selected_articles.filter(published_date__gte=article_date_from)
    if article_date_to:
        selected_articles = selected_articles.filter(published_date__lte=article_date_to)
    final_article_ids = list(selected_articles.order_by("id").values_list("id", flat=True))
    selected_platforms = Platform.objects.filter(id__in=set(platform_ids), status=PlatformStatus.ENABLED)
    if use_all_enabled_platforms:
        selected_platforms = Platform.objects.filter(status=PlatformStatus.ENABLED)
    final_platform_ids = list(selected_platforms.order_by("id").values_list("id", flat=True))
    if not final_article_ids:
        raise ValueError("检测批次必须选择至少一篇有效原创文章。")
    if not final_platform_ids:
        raise ValueError("检测批次必须选择至少一个启用平台。")
    with transaction.atomic():
        batch, _ = DetectionBatch.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "trigger": trigger,
                "article_ids": final_article_ids,
                "platform_ids": final_platform_ids,
                "article_date_from": article_date_from,
                "article_date_to": article_date_to,
                "created_by": created_by,
            },
        )
        for article_id in batch.article_ids:
            for platform_id in batch.platform_ids:
                DetectionResult.objects.get_or_create(batch=batch, article_id=article_id, platform_id=platform_id)
    return batch


def automatic_idempotency_key(*, week: str, hour: str) -> str:
    return hashlib.sha256(f"automatic:{week}:{hour}".encode()).hexdigest()


def batch_statistics(batch: DetectionBatch) -> dict[str, object]:
    results = list(batch.results.values("article_id", "status"))
    platform_total = len(batch.platform_ids)
    article_total = len(batch.article_ids)
    per_article: list[dict[str, object]] = []
    for article_id in batch.article_ids:
        article_results = [item for item in results if item["article_id"] == article_id]
        found = sum(item["status"] == "FOUND" for item in article_results)
        completed = sum(item["status"] in {"FOUND", "NOT_FOUND"} for item in article_results)
        per_article.append(
            {
                "article_id": article_id,
                "reposted_platform_count": found,
                "platform_repost_rate": found / platform_total if platform_total else 0,
                "completed_platform_count": completed,
                "detection_completion_rate": completed / platform_total if platform_total else 0,
            }
        )
    reposted_articles = sum(cast(int, item["reposted_platform_count"]) > 0 for item in per_article)
    completed_cells = sum(item["status"] in {"FOUND", "NOT_FOUND"} for item in results)
    return {
        "article_total": article_total,
        "platform_total": platform_total,
        "article_reposted_count": reposted_articles,
        "article_repost_rate": reposted_articles / article_total if article_total else 0,
        "completed_cell_count": completed_cells,
        "detection_completion_rate": (
            completed_cells / (article_total * platform_total) if article_total and platform_total else 0
        ),
        "per_article": per_article,
    }
