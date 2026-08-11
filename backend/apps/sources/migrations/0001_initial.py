import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_weeklyonstock(apps, schema_editor):
    Source = apps.get_model("sources", "Source")
    Source.objects.update_or_create(
        code="WEEKLYONSTOCK",
        defaults={
            "name": "证券市场周刊",
            "base_url": "https://www.weeklyonstock.com/",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Source",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "code",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="来源代码只能包含大写英文字母、数字和下划线。",
                                regex="^[A-Z0-9_]+$",
                            )
                        ],
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("base_url", models.URLField(max_length=2048)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "sources_source", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="SourceIngestToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("token_prefix", models.CharField(db_index=True, max_length=16)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ingest_tokens",
                        to="sources.source",
                    ),
                ),
            ],
            options={"db_table": "sources_ingest_token", "ordering": ["-created_at", "-id"]},
        ),
        migrations.RunPython(seed_weeklyonstock, migrations.RunPython.noop),
    ]
