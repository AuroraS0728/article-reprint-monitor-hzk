import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("articles", "0004_article_duplicate_protection"),
        ("sources", "0002_searchrun"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticleIngestConflict",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=500)),
                ("normalized_title", models.CharField(db_index=True, max_length=500)),
                ("author", models.CharField(max_length=255)),
                ("published_at", models.DateTimeField()),
                ("published_date", models.DateField(db_index=True)),
                ("original_url", models.URLField(max_length=2048)),
                ("canonical_original_url", models.URLField(max_length=2048)),
                ("source_item_key", models.CharField(max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "待人工确认"),
                            ("APPROVED_AS_NEW", "批准为独立文章"),
                            ("LINKED_TO_EXISTING", "关联到已有文章"),
                            ("REJECTED", "已拒绝"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_reason", models.TextField(blank=True, default="")),
                (
                    "created_article",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_source_conflicts",
                        to="articles.article",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_article_ingest_conflicts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "existing_article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_conflicts",
                        to="articles.article",
                    ),
                ),
                (
                    "linked_article",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="linked_source_conflicts",
                        to="articles.article",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_article_ingest_conflicts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="article_ingest_conflicts",
                        to="sources.source",
                    ),
                ),
            ],
            options={
                "db_table": "sources_article_ingest_conflict",
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source", "source_item_key"),
                        name="uniq_source_ingest_conflict_item",
                    )
                ],
            },
        )
    ]
