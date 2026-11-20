from django.db import migrations


def seed_booking_minimum_payment_percent(apps, schema_editor):
    SystemParameter = apps.get_model("system_settings", "SystemParameter")
    Project = apps.get_model("inventory", "Project")
    for project in Project.objects.all():
        SystemParameter.objects.get_or_create(
            organization_id=project.organization_id,
            project_id=project.pk,
            parameter_key="booking_minimum_payment_percent",
            defaults={
                "parameter_name": "Booking minimum payment percent",
                "value": 10,
                "data_type": "integer",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0011_phase8_plot_status_master_data")]
    operations = [migrations.RunPython(seed_booking_minimum_payment_percent, migrations.RunPython.noop)]
