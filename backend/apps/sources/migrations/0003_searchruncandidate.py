from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("sources", "0003_articleingestconflict")]

    operations = [
        migrations.CreateModel(
            name="SearchRunCandidate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=500)),
                ("site_name", models.CharField(blank=True, max_length=255)),
                ("site_domain", models.CharField(blank=True, db_index=True, max_length=253)),
                ("raw_url", models.URLField(max_length=2048)),
                ("canonical_url", models.URLField(max_length=2048)),
                ("canonical_url_hash", models.CharField(max_length=64)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                (
                    "disposition",
                    models.CharField(
                        choices=[
                            ("PENDING", "待比对"),
                            ("EXCLUDED_SOURCE", "原创来源链接"),
                            ("EXCLUDED_ORIGINAL", "原创文章链接"),
                            ("EXCLUDED_TOO_EARLY", "发布时间早于原创"),
                            ("NOT_MATCHED", "未匹配"),
                            ("MATCHED", "已匹配转载"),
                        ],
                        default="PENDING",
                        max_length=32,
                    ),
                ),
                ("similarity_score", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("reason_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "search_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="candidates",
                        to="sources.searchrun",
                    ),
                ),
            ],
            options={"db_table": "sources_search_run_candidate", "ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="searchruncandidate",
            constraint=models.UniqueConstraint(
                fields=("search_run", "canonical_url_hash"), name="uniq_search_run_candidate_url"
            ),
        ),
    ]
