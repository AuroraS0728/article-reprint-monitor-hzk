from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.models import SearchCandidateDisposition, SearchRun, SearchRunCandidate
from apps.sources.services import (
    _candidate_as_search_candidate,
    _candidate_meets_retention_threshold,
    _refresh_search_run_counts,
    automatic_repost_site_for_candidate,
    classify_owned_channel,
    compare_titles,
    upsert_global_repost,
)


class Command(BaseCommand):
    help = "Apply automatic repost and positive owned-channel rules to retained candidates."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Only report proposed changes.")
        parser.add_argument(
            "--prune-below-threshold",
            action="store_true",
            help="Remove prior automatic repost candidates below the configured retention threshold.",
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        prune_below_threshold = bool(options["prune_below_threshold"])
        changed_runs: set[int] = set()
        counts: Counter[str] = Counter()
        changed = 0
        candidates = SearchRunCandidate.objects.select_related("search_run__article").order_by("id")
        for record in candidates:
            article = record.search_run.article
            candidate = _candidate_as_search_candidate(record)
            match = compare_titles(article.title, candidate)
            if not _candidate_meets_retention_threshold(match=match):
                if prune_below_threshold and record.reason_code.startswith("AUTO_REPOST_SITE_DOMAIN:"):
                    counts["below_threshold_pruned"] += 1
                    changed += 1
                    if not dry_run:
                        self._prune_automatic_candidate(record)
                        changed_runs.add(record.search_run_id)
                continue
            site = automatic_repost_site_for_candidate(candidate)
            relation, owned_channel, reason = classify_owned_channel(candidate)
            if relation != ContentRelation.OWNED and site is None:
                continue
            if record.reason_code == "MANUAL_REPOST":
                counts["manual_repost_skipped"] += 1
                continue
            if relation == ContentRelation.OWNED:
                rule_code = f"OWNED_CHANNEL:{owned_channel.code}" if owned_channel else "OWNED_CHANNEL"
            else:
                if site is None:
                    continue
                relation = ContentRelation.REPOST
                owned_channel = None
                rule_code = f"AUTO_REPOST_SITE_DOMAIN:{site.code}"
            counts[rule_code] += 1
            if (
                record.content_relation == relation
                and record.reason_code == rule_code
                and record.owned_channel_id == (owned_channel.id if owned_channel else None)
            ):
                continue
            changed += 1
            if dry_run:
                continue
            now = timezone.now()
            global_record, _ = upsert_global_repost(
                article=article,
                candidate=candidate,
                match=match,
                found_at=now,
                content_relation=relation,
                owned_channel=owned_channel,
                classification_reason=rule_code,
            )
            global_record.content_relation = relation
            global_record.owned_channel = owned_channel
            global_record.classification_reason = rule_code
            global_record.classified_at = now
            global_record.is_valid = True
            global_record.save(
                update_fields=[
                    "content_relation",
                    "owned_channel",
                    "classification_reason",
                    "classified_at",
                    "is_valid",
                    "updated_at",
                ]
            )
            record.disposition = SearchCandidateDisposition.MATCHED
            record.reason_code = rule_code
            record.content_relation = relation
            record.owned_channel = owned_channel
            record.classification_reason = rule_code
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

    @staticmethod
    def _prune_automatic_candidate(record: SearchRunCandidate) -> None:
        """Delete an invalid automatic candidate without revoking manual evidence."""
        article = record.search_run.article
        canonical_url_hash = record.canonical_url_hash
        remaining = SearchRunCandidate.objects.filter(
            search_run__article=article,
            canonical_url_hash=canonical_url_hash,
        ).exclude(pk=record.pk)
        has_manual_confirmation = remaining.filter(reason_code="MANUAL_REPOST").exists()
        has_retained_automatic_confirmation = False
        for related in remaining.select_related("search_run__article"):
            related_match = compare_titles(related.search_run.article.title, _candidate_as_search_candidate(related))
            if _candidate_meets_retention_threshold(match=related_match):
                has_retained_automatic_confirmation = True
                break

        record.delete()
        if has_manual_confirmation or has_retained_automatic_confirmation:
            return
        RepostRecord.objects.filter(
            article=article,
            canonical_url_hash=canonical_url_hash,
            content_relation=ContentRelation.REPOST,
            classification_reason__startswith="AUTO_REPOST_SITE_DOMAIN:",
        ).delete()
