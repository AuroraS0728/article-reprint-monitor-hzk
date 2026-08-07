from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("articles", "0002_articleimportjob_uploaded_file"), ("platforms", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="RepostRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_url", models.URLField(max_length=2048)),
                ("normalized_url", models.URLField(max_length=2048)),
                ("normalized_url_hash", models.CharField(max_length=64)),
                ("final_url", models.URLField(blank=True, max_length=2048)),
                ("repost_title", models.CharField(max_length=500)),
                ("repost_published_at", models.DateTimeField(blank=True, null=True)),
                ("first_discovered_at", models.DateTimeField()),
                ("last_checked_at", models.DateTimeField()),
                ("data_source", models.CharField(max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repost_records",
                        to="articles.article",
                    ),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="repost_records",
                        to="platforms.platform",
                    ),
                ),
            ],
            options={
                "db_table": "reposts_repost_record",
                "ordering": ["repost_published_at", "first_discovered_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="repostrecord",
            constraint=models.UniqueConstraint(
                fields=("article", "platform", "normalized_url_hash"), name="uniq_repost_url"
            ),
        ),
    ]
