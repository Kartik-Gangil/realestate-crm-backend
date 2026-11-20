from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0006_alter_auditlog_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integrationconfiguration",
            name="integration_type",
            field=models.CharField(choices=[("email", "Email"), ("sms", "SMS"), ("whatsapp", "WhatsApp"), ("document_storage", "Document storage"), ("meta_ads", "Meta Ads"), ("google_ads", "Google Ads")], max_length=32),
        ),
    ]
