from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("monitoring", "0001_initial")]

    operations = [
        migrations.RenameIndex(
            model_name="detectionresult",
            new_name="monitoring__batch_i_3eb17a_idx",
            old_name="monitoring_d_batch_i_7a79c3_idx",
        ),
        migrations.RenameIndex(
            model_name="detectionresult",
            new_name="monitoring__article_84af91_idx",
            old_name="monitoring_d_article_01db2c_idx",
        ),
    ]
