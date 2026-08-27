from django.db import migrations


CATALOGUE = {
    "payments": ("view", "add", "edit", "refund", "adjust", "cancel", "export", "receipt"),
    "registry": ("view", "add", "edit", "delete", "cancel", "documents", "charges", "status", "reports"),
}


def add_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    Role = apps.get_model("organizations", "OrganizationRole")
    for module, actions in CATALOGUE.items():
        for action in actions:
            permission, _ = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={"name": f"{action.title()} {module.title()}"},
            )
            for role in Role.objects.filter(code="admin"):
                role.permissions.add(permission)
            if action in {"view", "add", "edit", "receipt"} and module == "payments":
                for role in Role.objects.filter(code="manager"):
                    role.permissions.add(permission)
            if module == "registry" and action in {"view", "add", "edit", "status"}:
                for role in Role.objects.filter(code="manager"):
                    role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0008_remove_organizationmembership_tab_permissions")]
    operations = [migrations.RunPython(add_permissions, migrations.RunPython.noop)]
