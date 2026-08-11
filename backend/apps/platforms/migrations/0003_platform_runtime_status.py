from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platforms", "0002_platform_confirmed_title_suffixes")]

    operations = [
        migrations.AddField(
            model_name="platform",
            name="last_success_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platform",
            name="last_failure_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platform",
            name="consecutive_failure_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="platform",
            name="last_failure_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
