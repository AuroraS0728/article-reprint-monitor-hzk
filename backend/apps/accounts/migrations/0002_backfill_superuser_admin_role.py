from django.db import migrations


def backfill_superuser_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).exclude(role="ADMIN").update(role="ADMIN", must_change_password=False)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(backfill_superuser_roles, migrations.RunPython.noop)]
