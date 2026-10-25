from django.db import migrations


# FR-P3-02/DM-P3-02: complete the global RBAC permission catalogue.


MODULES = (
    "dashboard", "leads", "assigned_leads", "customers", "telecalling", "follow_ups",
    "site_visits", "plots", "payments", "registry", "loans", "employees", "documents",
    "expenses", "communication", "activity", "reports", "role", "settings", "employee",
    "attendance", "leave",
)
STANDARD_ACTIONS = ("view", "add", "edit", "delete", "export", "approve")


def complete_permission_catalogue(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    permissions = []
    for module in MODULES:
        for action in STANDARD_ACTIONS:
            permission, _ = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={"name": f"{action.title()} {module.replace('_', ' ').title()}"},
            )
            permissions.append(permission)

    for role in OrganizationRole.objects.filter(code="admin"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0014_manager_settings_view")]

    operations = [migrations.RunPython(complete_permission_catalogue, migrations.RunPython.noop)]
