from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platforms", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="platform",
            name="confirmed_title_suffixes",
            field=models.JSONField(blank=True, default=list),
        )
    ]
