from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("articles", "0003_source_global_monitoring"), ("sources", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="SearchRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=50)),
                ("query", models.TextField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "待执行"), ("RUNNING", "执行中"), ("SUCCESS", "成功"), ("ERROR", "失败")],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("candidate_count", models.PositiveIntegerField(default=0)),
                ("matched_count", models.PositiveIntegerField(default=0)),
                ("new_repost_count", models.PositiveIntegerField(default=0)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="search_runs",
                        to="articles.article",
                    ),
                ),
            ],
            options={
                "db_table": "sources_search_run",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["article", "status", "created_at"], name="sources_sea_article_8b0a7e_idx")
                ],
            },
        )
    ]
