from django.db import migrations


def seed_site_visit_reminder_days(apps, schema_editor):
    Project = apps.get_model("inventory", "Project")
    SystemParameter = apps.get_model("system_settings", "SystemParameter")
    for project in Project.objects.all().iterator():
        SystemParameter.objects.get_or_create(
            organization_id=project.organization_id,
            project_id=project.pk,
            parameter_key="site_visit_reminder_days",
            defaults={
                "parameter_name": "Site visit reminder days",
                "value": 1,
                "data_type": "integer",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0008_integration_last_synced_at"),
        ("inventory", "0015_require_project_references"),
    ]

    operations = [
        migrations.RunPython(seed_site_visit_reminder_days, migrations.RunPython.noop),
    ]
