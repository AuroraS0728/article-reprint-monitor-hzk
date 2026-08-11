from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import apps.reports.models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monitoring", "0002_rename_indexes"),
    ]
    operations = [
        migrations.CreateModel(
            name="SMTPConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("host", models.CharField(blank=True, max_length=253)),
                ("port", models.PositiveIntegerField(default=587)),
                ("username", models.CharField(blank=True, max_length=320)),
                ("from_email", models.EmailField(blank=True, max_length=254)),
                ("encrypted_authorization_code", models.TextField(blank=True)),
                ("recipients", models.JSONField(default=list)),
                ("cc_recipients", models.JSONField(default=list)),
                ("use_tls", models.BooleanField(default=True)),
                ("enabled", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"db_table": "reports_smtp_configuration"},
        ),
        migrations.CreateModel(
            name="GeneratedReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_type", models.CharField(choices=[("DAILY", "日报"), ("WEEKLY", "周报")], max_length=16)),
                ("report_date", models.DateField(db_index=True, help_text="日报日期或周报周一日期")),
                ("version", models.PositiveSmallIntegerField(default=1)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("report_file", models.FileField(max_length=300, upload_to=apps.reports.models.report_upload_path)),
                ("file_sha256", models.CharField(max_length=64)),
                ("statistics_range", models.JSONField(default=dict)),
                (
                    "generated_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "snapshot",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="monitoring.statussnapshot"),
                ),
            ],
            options={"db_table": "reports_generated_report", "ordering": ["-report_date", "-version", "-id"]},
        ),
        migrations.CreateModel(
            name="ReportEmailDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "待发送"), ("SENT", "已发送"), ("FAILED", "发送失败")],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("recipients", models.JSONField(default=list)),
                ("cc_recipients", models.JSONField(default=list)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("error_message", models.CharField(blank=True, max_length=1000)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="email_deliveries",
                        to="reports.generatedreport",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"db_table": "reports_email_delivery", "ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="generatedreport",
            constraint=models.UniqueConstraint(
                fields=("report_type", "report_date", "version"), name="uniq_report_version"
            ),
        ),
    ]
