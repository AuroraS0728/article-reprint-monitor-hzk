from __future__ import annotations

from datetime import timedelta
from typing import Any

import redis
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.articles.models import Article, ArticleMonitoringStatus

from .services import purge_expired_source_articles, search_article


@shared_task(bind=True, max_retries=3, name="apps.sources.tasks.search_article_reposts")
def search_article_reposts(
    self: Any, article_id: int, *, manual: bool = False
) -> int | str:
    lock_client = redis.Redis.from_url(settings.REDIS_URL)
    lock = lock_client.lock(
        f"global-repost-search:article:{article_id}",
        timeout=settings.SEARCH_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        return "LOCKED"
    try:
        article = Article.objects.select_related("source").filter(pk=article_id).first()
        if article is None:
            return "ARTICLE_NOT_FOUND"
        now = timezone.now()
        if not manual and article.monitoring_status != ArticleMonitoringStatus.ACTIVE:
            return "NOT_ACTIVE"
        if not manual and (not article.monitor_until or now >= article.monitor_until):
            article.monitoring_status = ArticleMonitoringStatus.COMPLETED
            article.next_search_at = None
            article.save(
                update_fields=["monitoring_status", "next_search_at", "updated_at"]
            )
            return "COMPLETED"
        run = search_article(article)
        if run.status == "ERROR" and run.error_code in {
            "SEARCH_PROVIDER_RATE_LIMITED",
            "SEARCH_PROVIDER_UNAVAILABLE",
            "SEARCH_PROVIDER_ERROR",
        }:
            raise self.retry(
                countdown=min(60 * (2 ** getattr(self.request, "retries", 0)), 900)
            )
        return run.id
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


@shared_task(name="apps.sources.tasks.schedule_due_article_searches")
def schedule_due_article_searches() -> int:
    now = timezone.now()
    with transaction.atomic():
        due_ids = list(
            Article.objects.select_for_update(skip_locked=True)
            .filter(
                monitoring_status=ArticleMonitoringStatus.ACTIVE,
                next_search_at__lte=now,
                monitor_until__gt=now,
            )
            .order_by("next_search_at")
            .values_list("id", flat=True)[: settings.SEARCH_SCHEDULER_BATCH_SIZE]
        )
        Article.objects.filter(id__in=due_ids).update(
            next_search_at=now + timedelta(minutes=5)
        )
    for article_id in due_ids:
        search_article_reposts.delay(article_id)
    return len(due_ids)


@shared_task(name="apps.sources.tasks.complete_expired_article_monitoring")
def complete_expired_article_monitoring() -> int:
    return Article.objects.filter(
        monitoring_status=ArticleMonitoringStatus.ACTIVE,
        monitor_until__lte=timezone.now(),
    ).update(monitoring_status=ArticleMonitoringStatus.COMPLETED, next_search_at=None)


@shared_task(name="apps.sources.tasks.purge_expired_monitoring_data")
def purge_expired_monitoring_data() -> dict[str, int]:
    return purge_expired_source_articles()
