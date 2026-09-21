from django.db import migrations


PERMISSIONS = {
    "expenses": (
        "view_own", "edit_own", "submit", "view_team", "approve", "manage_categories",
        "process_payment", "process_reimbursement", "reports",
    ),
}


def seed_expense_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    Role = apps.get_model("organizations", "OrganizationRole")
    for module, actions in PERMISSIONS.items():
        for action in actions:
            permission, _ = Permission.objects.get_or_create(
                module=module, action=action,
                defaults={"name": f"{action.replace('_', ' ').title()} Expenses"},
            )
            for role in Role.objects.filter(code="admin"):
                role.permissions.add(permission)
            if action in {"view_own", "edit_own", "submit"}:
                for role in Role.objects.filter(code__in=["manager", "telecaller"]):
                    role.permissions.add(permission)
            if action in {"view_team", "approve"}:
                for role in Role.objects.filter(code="manager"):
                    role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0009_payment_registry_permissions")]
    operations = [migrations.RunPython(seed_expense_permissions, migrations.RunPython.noop)]
