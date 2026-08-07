from django.db import migrations, models

import apps.reports.models


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="generatedreport",
            name="report_file",
            field=models.FileField(blank=True, max_length=300, upload_to=apps.reports.models.report_upload_path),
        )
    ]
