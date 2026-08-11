import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_duplicate_slots(apps, schema_editor):
    Article = apps.get_model("articles", "Article")
    current_group = None
    slot = 0
    for article in Article.objects.order_by("normalized_title", "published_date", "id").iterator():
        group = (article.normalized_title, article.published_date)
        if group != current_group:
            current_group = group
            slot = 0
        article.duplicate_slot = slot
        update_fields = ["duplicate_slot"]
        if slot > 0:
            article.duplicate_approved_by = None
            article.duplicate_approved_at = None
            article.duplicate_reason = "LEGACY_MIGRATION_EXISTING_DUPLICATE"
            update_fields.extend(["duplicate_approved_by", "duplicate_approved_at", "duplicate_reason"])
        article.save(update_fields=update_fields)
        slot += 1


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("articles", "0003_source_global_monitoring"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="duplicate_slot",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="article",
            name="duplicate_approved_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_duplicate_articles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="article",
            name="duplicate_approved_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="article",
            name="duplicate_reason",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.RunPython(backfill_duplicate_slots, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                fields=("normalized_title", "published_date", "duplicate_slot"),
                name="uniq_article_title_date_slot",
            ),
        ),
    ]
