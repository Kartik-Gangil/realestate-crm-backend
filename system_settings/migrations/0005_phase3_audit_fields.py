import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inventory", "0015_require_project_references"),
        ("system_settings", "0004_alter_masterdata_options"),
    ]

    operations = [
        migrations.RenameField(model_name="auditlog", old_name="actor", new_name="user"),
        migrations.RenameField(model_name="auditlog", old_name="timestamp", new_name="created_at"),
        migrations.AddField(
            model_name="auditlog",
            name="method",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="route",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="payload_before",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="payload_after",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="project",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="settings_audit_logs", to="inventory.project"),
        ),
    ]
