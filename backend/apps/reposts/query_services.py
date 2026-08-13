from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from django.db.models import Count, Exists, OuterRef, Q, QuerySet

from apps.articles.models import Article

from .models import ContentRelation, RepostRecord


@dataclass(frozen=True)
class RepostQueryFilters:
    published_from: date | None = None
    published_to: date | None = None
    channel: str = ""
    section: str = ""
    monitoring_status: str = ""
    has_repost: bool | None = None
    site_domain: str = ""
    q: str = ""


def filtered_repost_articles(filters: RepostQueryFilters, *, as_of: datetime) -> QuerySet[Article]:
    records = RepostRecord.objects.filter(
        article_id=OuterRef("pk"),
        is_valid=True,
        content_relation=ContentRelation.REPOST,
        created_at__lte=as_of,
    )
    queryset = Article.objects.filter(Q(retention_until__isnull=True) | Q(retention_until__gte=as_of))
    if filters.published_from:
        queryset = queryset.filter(published_date__gte=filters.published_from)
    if filters.published_to:
        queryset = queryset.filter(published_date__lte=filters.published_to)
    if filters.channel:
        queryset = queryset.filter(Q(channel_code=filters.channel) | Q(channel_name=filters.channel))
    if filters.section:
        queryset = queryset.filter(Q(section_code=filters.section) | Q(section_name=filters.section))
    if filters.monitoring_status:
        queryset = queryset.filter(monitoring_status=filters.monitoring_status)
    if filters.q:
        queryset = queryset.filter(title__icontains=filters.q)
    if filters.site_domain:
        queryset = queryset.filter(Exists(records.filter(site_domain__iexact=filters.site_domain)))
    if filters.has_repost is not None:
        queryset = queryset.filter(Exists(records) if filters.has_repost else ~Exists(records))
    return queryset.distinct().order_by("-published_at", "-published_date", "-id")


def result_summary(queryset: QuerySet[Article], *, as_of: datetime) -> dict[str, int]:
    article_ids = queryset.values_list("id", flat=True)
    records = RepostRecord.objects.filter(
        article_id__in=article_ids,
        is_valid=True,
        content_relation=ContentRelation.REPOST,
        created_at__lte=as_of,
    )
    return {
        "article_count": queryset.count(),
        "repost_article_count": records.values("article_id").distinct().count(),
        "repost_site_count": records.exclude(site_domain="").values("site_domain").distinct().count(),
        "repost_url_count": records.values("article_id", "canonical_url").distinct().count(),
    }


def monitoring_status_counts(queryset: QuerySet[Article]) -> dict[str, int]:
    """Return status totals for the whole filtered set, never just the visible page."""
    counts = {"PENDING": 0, "ACTIVE": 0, "COMPLETED": 0, "ERROR": 0}
    for row in queryset.values("monitoring_status").annotate(count=Count("id")):
        status = str(row["monitoring_status"])
        if status in counts:
            counts[status] = int(row["count"])
    return counts


def repost_trend(queryset: QuerySet[Article], *, as_of: datetime) -> list[dict[str, object]]:
    records = RepostRecord.objects.filter(
        article__in=queryset,
        is_valid=True,
        content_relation=ContentRelation.REPOST,
        created_at__lte=as_of,
    )
    trend: dict[date, dict[str, object]] = {}
    for article in queryset.only("id", "published_date"):
        trend.setdefault(
            article.published_date,
            {
                "published_date": article.published_date.isoformat(),
                "article_count": 0,
                "site_count": 0,
                "repost_url_count": 0,
            },
        )
        trend[article.published_date]["article_count"] = cast(int, trend[article.published_date]["article_count"]) + 1
    grouped: dict[date, set[tuple[int, str]]] = {}
    sites: dict[date, set[str]] = {}
    article_dates = {article.id: article.published_date for article in queryset.only("id", "published_date")}
    for record in records.only("article_id", "canonical_url", "normalized_url", "site_domain"):
        published_date = article_dates[record.article_id]
        grouped.setdefault(published_date, set()).add(
            (record.article_id, record.canonical_url or record.normalized_url)
        )
        if record.site_domain:
            sites.setdefault(published_date, set()).add(record.site_domain)
    for published_date, values in grouped.items():
        trend[published_date]["repost_url_count"] = len(values)
        trend[published_date]["site_count"] = len(sites.get(published_date, set()))
    return [trend[item] for item in sorted(trend)]


def channel_options() -> list[dict[str, str]]:
    rows = (
        Article.objects.exclude(channel_code="")
        .values("channel_code", "channel_name")
        .annotate(count=Count("id"))
        .order_by("channel_name", "channel_code")
    )
    return [
        {
            "code": row["channel_code"],
            "name": row["channel_name"] or row["channel_code"],
        }
        for row in rows
    ]


def section_options() -> list[dict[str, str]]:
    rows = (
        Article.objects.exclude(section_code="")
        .values("section_code", "section_name")
        .annotate(count=Count("id"))
        .order_by("section_name", "section_code")
    )
    return [
        {
            "code": row["section_code"],
            "name": row["section_name"] or row["section_code"],
        }
        for row in rows
    ]
