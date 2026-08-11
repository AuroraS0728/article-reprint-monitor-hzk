import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("articles", "0002_articleimportjob_uploaded_file"), ("sources", "0001_initial")]
    operations = [
        migrations.RemoveConstraint(model_name="article", name="uniq_article_title_date"),
        migrations.AddField(
            model_name="article", name="author", field=models.CharField(blank=True, default="", max_length=255)
        ),
        migrations.AddField(
            model_name="article", name="discovered_at", field=models.DateTimeField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="article",
            name="ingest_method",
            field=models.CharField(
                choices=[
                    ("MANUAL", "手工录入"),
                    ("EXCEL", "Excel 导入"),
                    ("BULK_PASTE", "批量粘贴"),
                    ("SOURCE_API", "来源接口"),
                ],
                db_index=True,
                default="MANUAL",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="article", name="last_searched_at", field=models.DateTimeField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="article", name="monitor_started_at", field=models.DateTimeField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="article", name="monitor_until", field=models.DateTimeField(blank=True, db_index=True, null=True)
        ),
        migrations.AddField(
            model_name="article",
            name="monitoring_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "待监测"),
                    ("ACTIVE", "监测中"),
                    ("COMPLETED", "已完成"),
                    ("ERROR", "异常"),
                ],
                db_index=True,
                default="PENDING",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="article",
            name="next_search_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="article", name="published_at", field=models.DateTimeField(blank=True, db_index=True, null=True)
        ),
        migrations.AddField(
            model_name="article",
            name="retention_until",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="article",
            name="source",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="articles",
                to="sources.source",
            ),
        ),
        migrations.AddField(
            model_name="article", name="source_item_key", field=models.CharField(blank=True, max_length=128, null=True)
        ),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(fields=("source", "source_item_key"), name="uniq_source_article_item"),
        ),
    ]
