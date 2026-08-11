from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("reposts", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="repostrecord",
            name="manual_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="manually_added_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="manually_added_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="manual_repost_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="is_valid",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="invalidated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="invalidated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invalidated_manual_repost_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="repostrecord",
            name="invalidation_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
