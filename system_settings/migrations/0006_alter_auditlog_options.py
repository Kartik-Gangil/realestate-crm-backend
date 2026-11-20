from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0005_phase3_audit_fields")]

    operations = [
        migrations.AlterModelOptions(
            name="auditlog",
            options={"ordering": ("-created_at", "-id")},
        ),
    ]
