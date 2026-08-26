from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

import django.db.models.deletion
from django.db import migrations, models


def backfill_global_fields(apps, schema_editor):
    RepostRecord = apps.get_model("reposts", "RepostRecord")
    PlatformDomain = apps.get_model("platforms", "PlatformDomain")
    seen: dict[tuple[int, str], Any] = {}
    for record in RepostRecord.objects.select_related("platform").order_by(
        "first_discovered_at", "id"
    ):
        canonical = record.normalized_url or record.final_url or record.original_url
        key = (record.article_id, canonical)
        if key in seen:
            keeper = seen[key]
            if record.last_checked_at > keeper.last_checked_at:
                keeper.last_checked_at = record.last_checked_at
                keeper.save(update_fields=["last_checked_at"])
            record.delete()
            continue
        domain_row = PlatformDomain.objects.filter(
            platform_id=record.platform_id
        ).first()
        domain = (
            domain_row.domain if domain_row else (urlsplit(canonical).hostname or "")
        )
        record.site_name = record.platform.name
        record.site_domain = domain.lower()
        record.raw_url = record.original_url
        record.canonical_url = canonical
        record.canonical_url_hash = sha256(canonical.encode("utf-8")).hexdigest()
        record.normalized_url_hash = sha256(canonical.encode("utf-8")).hexdigest()
        record.result_title = record.repost_title
        record.normalized_result_title = record.repost_title
        record.result_published_at = record.repost_published_at
        record.first_found_at = record.first_discovered_at
        record.last_seen_at = record.last_checked_at
        record.save()
        seen[key] = record


class Migration(migrations.Migration):
    dependencies = [
        ("articles", "0003_source_global_monitoring"),
        ("reposts", "0002_manual_supplement_fields"),
    ]
    operations = [
        migrations.AlterField(
            model_name="repostrecord",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="repost_records",
                to="platforms.platform",
            ),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="availability_status",
            field=models.CharField(
                choices=[
                    ("UNKNOWN", "未知"),
                    ("AVAILABLE", "正常"),
                    ("UNAVAILABLE", "不可访问"),
                    ("REMOVED", "已删除"),
                ],
                db_index=True,
                default="UNKNOWN",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="canonical_url",
            field=models.URLField(blank=True, max_length=2048, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="canonical_url_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="first_found_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="last_availability_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="normalized_result_title",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="raw_url",
            field=models.URLField(blank=True, max_length=2048),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="result_published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="result_title",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="search_provider",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="similarity_score",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=5, null=True
            ),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="site_domain",
            field=models.CharField(blank=True, db_index=True, max_length=253),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="site_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(backfill_global_fields, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="repostrecord",
            constraint=models.UniqueConstraint(
                fields=("article", "canonical_url_hash"),
                name="uniq_article_canonical_hash",
            ),
        ),
    ]
