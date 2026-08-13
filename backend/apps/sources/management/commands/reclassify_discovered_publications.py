from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import OperationLog
from apps.reposts.models import ContentRelation, RepostRecord
from apps.sources.services import classify_owned_channel
from search_providers.types import SearchCandidate


class Command(BaseCommand):
    help = "Reclassify retained discovered publications using OwnedChannel rules without deleting evidence."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Only report proposed changes.")

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        counts: Counter[str] = Counter()
        changed = 0
        for record in RepostRecord.objects.filter(data_source__startswith="SEARCH_PROVIDER:").select_related(
            "owned_channel"
        ):
            candidate = SearchCandidate(
                title=record.result_title or record.repost_title,
                url=record.canonical_url or record.normalized_url,
                site_name=record.site_name,
                domain=record.site_domain,
                published_at=record.result_published_at,
                provider=record.search_provider,
            )
            relation, owned_channel, reason = classify_owned_channel(candidate)
            counts[relation] += 1
            if (
                relation == record.content_relation
                and (owned_channel.id if owned_channel else None) == record.owned_channel_id
                and reason == record.classification_reason
            ):
                continue
            changed += 1
            if not dry_run:
                before_data = {
                    "content_relation": record.content_relation,
                    "owned_channel_id": record.owned_channel_id,
                    "classification_reason": record.classification_reason,
                }
                record.content_relation = relation
                record.owned_channel = owned_channel
                record.classification_reason = reason
                record.classified_at = timezone.now()
                record.save(
                    update_fields=[
                        "content_relation",
                        "owned_channel",
                        "classification_reason",
                        "classified_at",
                        "updated_at",
                    ]
                )
                OperationLog.objects.create(
                    action_type="REPOST_CLASSIFICATION_CHANGED",
                    target_type="RepostRecord",
                    target_id=str(record.id),
                    before_data=before_data,
                    after_data={
                        "content_relation": relation,
                        "owned_channel_id": owned_channel.id if owned_channel else None,
                        "classification_reason": reason,
                        "command": "reclassify_discovered_publications",
                    },
                )
        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"{mode}: OWNED={counts[ContentRelation.OWNED]} REPOST={counts[ContentRelation.REPOST]} "
            f"REVIEW_REQUIRED={counts[ContentRelation.REVIEW_REQUIRED]} changed={changed}"
        )
