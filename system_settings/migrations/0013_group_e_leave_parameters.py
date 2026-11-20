from django.db import migrations


PARAMETERS = (
    ("leave_casual_days_per_year", "Casual leave days per year", 12),
    ("leave_sick_days_per_year", "Sick leave days per year", 6),
    ("leave_paid_days_per_year", "Paid leave days per year", 15),
)


def provision_leave_parameters(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    SystemParameter = apps.get_model("system_settings", "SystemParameter")
    for organization in Organization.objects.all().iterator():
        for key, name, default in PARAMETERS:
            SystemParameter.objects.get_or_create(
                organization=organization,
                project=None,
                parameter_key=key,
                defaults={
                    "category": "hr",
                    "parameter_name": name,
                    "value": default,
                    "data_type": "integer",
                    "description": "Calendar-year leave allocation; no carry-forward.",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0029_group_e_roles_hr_and_accounts"),
        ("system_settings", "0012_booking_minimum_payment_percent"),
    ]
    operations = [migrations.RunPython(provision_leave_parameters, migrations.RunPython.noop)]

