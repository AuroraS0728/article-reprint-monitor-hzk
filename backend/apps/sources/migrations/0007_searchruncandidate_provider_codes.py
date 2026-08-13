from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sources", "0006_searchproviderconfiguration")]

    operations = [
        migrations.AddField(
            model_name="searchruncandidate",
            name="provider_codes",
            field=models.JSONField(default=list),
        ),
    ]
