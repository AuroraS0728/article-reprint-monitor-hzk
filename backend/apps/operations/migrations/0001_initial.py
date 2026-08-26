from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import apps.operations.models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="DatabaseBackup",
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
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RUNNING", "运行中"),
                            ("SUCCEEDED", "成功"),
                            ("FAILED", "失败"),
                            ("SKIPPED", "跳过"),
                        ],
                        default="RUNNING",
                        max_length=16,
                    ),
                ),
                (
                    "backup_file",
                    models.FileField(
                        blank=True,
                        max_length=300,
                        upload_to=apps.operations.models.database_backup_path,
                    ),
                ),
                ("file_sha256", models.CharField(blank=True, max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("error_message", models.CharField(blank=True, max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "operations_database_backup",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="MaintenanceRun",
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
                ("operation_name", models.CharField(max_length=100)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RUNNING", "运行中"),
                            ("SUCCEEDED", "成功"),
                            ("FAILED", "失败"),
                            ("SKIPPED", "跳过"),
                        ],
                        default="RUNNING",
                        max_length=16,
                    ),
                ),
                ("details", models.JSONField(default=dict)),
                ("error_message", models.CharField(blank=True, max_length=1000)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "operations_maintenance_run",
                "ordering": ["-started_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="SystemRuntimeConfiguration",
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
                ("maintenance_enabled", models.BooleanField(default=True)),
                ("database_backup_enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "operations_system_runtime_configuration"},
        ),
    ]
