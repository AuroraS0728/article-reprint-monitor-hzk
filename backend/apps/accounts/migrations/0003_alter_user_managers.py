from django.db import migrations

import apps.accounts.models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_backfill_superuser_admin_role")]

    operations = [
        migrations.AlterModelManagers(
            name="user",
            managers=[("objects", apps.accounts.models.RepostUserManager())],
        ),
    ]
