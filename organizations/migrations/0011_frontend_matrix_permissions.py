from django.db import migrations


MISSING_MODULES = {
    "assigned_leads": ("view", "add", "edit", "delete", "export"),
    "site_visits": ("view", "add", "edit", "delete", "export"),
    "loans": ("view", "add", "edit", "delete", "export"),
}


def add_frontend_matrix_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    created = []
    for module, actions in MISSING_MODULES.items():
        for action in actions:
            permission, _ = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={"name": f"{action.title()} {module.replace('_', ' ').title()}"},
            )
            created.append(permission)

    for role in OrganizationRole.objects.filter(code="admin"):
        role.permissions.add(*created)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0010_telecalling_follow_up_permissions")]

    operations = [migrations.RunPython(add_frontend_matrix_permissions, migrations.RunPython.noop)]
