from django.db import migrations


TEAM_VIEW_MODULES = ("leads", "plots", "documents", "site_visits", "telecalling")


def add_manager_team_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    for module in TEAM_VIEW_MODULES:
        permission, _ = Permission.objects.get_or_create(
            module=module,
            action="view_team",
            defaults={"name": f"View team {module.replace('_', ' ')}", "scope": "project"},
        )
        for role in OrganizationRole.objects.filter(code="manager"):
            role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0020_alter_organizationmembership_access_scope")]
    operations = [migrations.RunPython(add_manager_team_permissions, migrations.RunPython.noop)]
