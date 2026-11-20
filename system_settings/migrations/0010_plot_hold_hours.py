from django.db import migrations


def seed_plot_hold_hours(apps, schema_editor):
    Project = apps.get_model("inventory", "Project")
    SystemParameter = apps.get_model("system_settings", "SystemParameter")
    for project in Project.objects.all().iterator():
        SystemParameter.objects.get_or_create(
            organization_id=project.organization_id,
            project_id=project.pk,
            parameter_key="plot_hold_hours",
            defaults={
                "parameter_name": "Plot hold hours",
                "value": 24,
                "data_type": "integer",
                "description": "Duration of temporary plot holds and blocks before expiry.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0009_site_visit_reminder_days"),
    ]

    operations = [migrations.RunPython(seed_plot_hold_hours, migrations.RunPython.noop)]
