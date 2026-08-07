from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("articles", "0002_articleimportjob_uploaded_file"),
        ("platforms", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="DetectionBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "trigger",
                    models.CharField(
                        choices=[("IMMEDIATE", "立即检测"), ("AUTOMATIC", "自动检测"), ("WEEKLY_FINAL", "周最终检测")],
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "待执行"),
                            ("RUNNING", "执行中"),
                            ("COMPLETED", "已完成"),
                            ("FAILED", "失败"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("article_ids", models.JSONField(default=list)),
                ("platform_ids", models.JSONField(default=list)),
                ("article_date_from", models.DateField(blank=True, null=True)),
                ("article_date_to", models.DateField(blank=True, null=True)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("scheduled_for", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_message", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"db_table": "monitoring_detection_batch", "ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="DetectionResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("FOUND", "1"), ("NOT_FOUND", "0"), ("UNKNOWN", "—")], default="UNKNOWN", max_length=16
                    ),
                ),
                ("reason_code", models.CharField(blank=True, max_length=64)),
                ("reason_message", models.CharField(blank=True, max_length=500)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("article", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="articles.article")),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="results",
                        to="monitoring.detectionbatch",
                    ),
                ),
                ("platform", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="platforms.platform")),
            ],
            options={"db_table": "monitoring_detection_result"},
        ),
        migrations.CreateModel(
            name="StatusSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "snapshot_type",
                    models.CharField(choices=[("DAILY", "日报状态"), ("WEEKLY", "周报状态")], max_length=16),
                ),
                ("cutoff_at", models.DateTimeField(db_index=True)),
                ("matrix_data", models.JSONField(default=dict)),
                ("statistics_data", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source_batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="monitoring.detectionbatch",
                    ),
                ),
            ],
            options={"db_table": "monitoring_status_snapshot"},
        ),
        migrations.CreateModel(
            name="TaskFailureLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_name", models.CharField(max_length=200)),
                ("error_type", models.CharField(max_length=100)),
                ("message", models.CharField(max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="monitoring.detectionbatch",
                    ),
                ),
            ],
            options={"db_table": "monitoring_task_failure_log", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="detectionresult",
            constraint=models.UniqueConstraint(
                fields=("batch", "article", "platform"), name="uniq_batch_article_platform"
            ),
        ),
        migrations.AddIndex(
            model_name="detectionresult",
            index=models.Index(fields=["batch", "status"], name="monitoring_d_batch_i_7a79c3_idx"),
        ),
        migrations.AddIndex(
            model_name="detectionresult",
            index=models.Index(fields=["article", "platform"], name="monitoring_d_article_01db2c_idx"),
        ),
        migrations.AddConstraint(
            model_name="statussnapshot",
            constraint=models.UniqueConstraint(fields=("snapshot_type", "cutoff_at"), name="uniq_snapshot_type_cutoff"),
        ),
    ]
