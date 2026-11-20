from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0007_phase4_ad_integrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="integrationconfiguration",
            name="last_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
