from django.db import migrations


def grant_manager_settings_view(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    settings_view = Permission.objects.filter(module="settings", action="view").first()
    if settings_view is None:
        return
    for role in OrganizationRole.objects.filter(code="manager", is_system=True):
        role.permissions.add(settings_view)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0013_expense_action_permissions")]

    operations = [migrations.RunPython(grant_manager_settings_view, migrations.RunPython.noop)]
