from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.models import SearchCandidateDisposition, SearchRun, SearchRunCandidate
from apps.sources.services import (
    _candidate_as_search_candidate,
    _refresh_search_run_counts,
    automatic_repost_site_for_candidate,
    classify_owned_channel,
    compare_titles,
    upsert_global_repost,
)


class Command(BaseCommand):
    help = "Confirm retained candidates for configured automatic repost media sites."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Only report proposed changes.")

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        changed_runs: set[int] = set()
        counts: Counter[str] = Counter()
        changed = 0
        candidates = SearchRunCandidate.objects.select_related("search_run__article").order_by("id")
        for record in candidates:
            article = record.search_run.article
            candidate = _candidate_as_search_candidate(record)
            match = compare_titles(article.title, candidate)
            site = automatic_repost_site_for_candidate(candidate)
            if site is None:
                continue
            relation, _, _ = classify_owned_channel(candidate)
            existing_owned = RepostRecord.objects.filter(
                article=article,
                canonical_url_hash=record.canonical_url_hash,
                content_relation=ContentRelation.OWNED,
                is_valid=True,
            ).exists()
            if relation == ContentRelation.OWNED or existing_owned:
                counts["owned_skipped"] += 1
                continue
            counts[site.code] += 1
            if (
                record.content_relation == ContentRelation.REPOST
                and record.reason_code == f"AUTO_REPOST_SITE_DOMAIN:{site.code}"
            ):
                continue
            changed += 1
            if dry_run:
                continue
            now = timezone.now()
            reason = f"AUTO_REPOST_SITE_DOMAIN:{site.code}"
            upsert_global_repost(
                article=article,
                candidate=candidate,
                match=match,
                found_at=now,
                content_relation=ContentRelation.REPOST,
                owned_channel=None,
                classification_reason=reason,
            )
            record.disposition = SearchCandidateDisposition.MATCHED
            record.reason_code = reason
            record.content_relation = ContentRelation.REPOST
            record.owned_channel = None
            record.classification_reason = reason
            record.classified_at = now
            record.save(
                update_fields=[
                    "disposition",
                    "reason_code",
                    "content_relation",
                    "owned_channel",
                    "classification_reason",
                    "classified_at",
                ]
            )
            changed_runs.add(record.search_run_id)
        if not dry_run:
            for run_id in changed_runs:
                _refresh_search_run_counts(SearchRun.objects.get(pk=run_id))
        mode = "DRY-RUN" if dry_run else "APPLIED"
        summary = " ".join(f"{code}={count}" for code, count in sorted(counts.items()))
        self.stdout.write(f"{mode}: changed={changed} {summary}".strip())
