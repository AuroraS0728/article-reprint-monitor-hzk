# Generated manually for the private Excel upload record.
from django.db import migrations, models

import apps.articles.models


class Migration(migrations.Migration):
    dependencies = [("articles", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="articleimportjob",
            name="uploaded_file",
            field=models.FileField(
                blank=True,
                max_length=300,
                upload_to=apps.articles.models.private_import_upload_path,
            ),
        ),
    ]
