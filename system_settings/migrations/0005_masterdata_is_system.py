from django.db import migrations, models


def protect_system_master_data(apps, schema_editor):
    MasterData = apps.get_model("system_settings", "MasterData")
    MasterData.objects.filter(master_type="call_disposition").update(is_system=True)


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0004_master_data_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="masterdata",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(protect_system_master_data, migrations.RunPython.noop),
    ]
