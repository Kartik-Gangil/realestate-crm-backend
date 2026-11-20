from django.db import migrations


def add_manager_employee_team_view(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    permission, _ = Permission.objects.get_or_create(
        module="employees",
        action="view_team",
        defaults={"name": "View team employees", "scope": "organization"},
    )
    for role in OrganizationRole.objects.filter(code="manager"):
        role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0021_manager_team_view_permissions")]
    operations = [migrations.RunPython(add_manager_employee_team_view, migrations.RunPython.noop)]
