from django.db import migrations


EXPENSE_PERMISSIONS = (
    ("view_own", "View own expenses"),
    ("edit_own", "Edit own expenses"),
    ("submit", "Submit expenses"),
    ("view_team", "View team expenses"),
    ("approve", "Approve expenses"),
    ("reject", "Reject expenses"),
    ("manage_categories", "Manage expense categories"),
    ("process_payment", "Process expense payments"),
    ("mark_paid", "Mark expenses as paid"),
    ("process_reimbursement", "Process expense reimbursements"),
    ("reports", "View expense reports"),
)


def add_expense_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    permissions = {
        action: Permission.objects.get_or_create(
            module="expenses",
            action=action,
            defaults={"name": name},
        )[0]
        for action, name in EXPENSE_PERMISSIONS
    }

    for role in OrganizationRole.objects.filter(code="admin"):
        role.permissions.add(*permissions.values())

    manager_permissions = [permissions[action] for action in ("view_team", "approve", "reject")]
    for role in OrganizationRole.objects.filter(code="manager", is_system=True):
        role.permissions.add(*manager_permissions)

    for role in OrganizationRole.objects.filter(permissions__module="expenses", permissions__action="approve").distinct():
        role.permissions.add(permissions["reject"])
    for role in OrganizationRole.objects.filter(permissions__module="expenses", permissions__action="process_payment").distinct():
        role.permissions.add(permissions["mark_paid"])


class Migration(migrations.Migration):
    dependencies = [("organizations", "0012_remove_default_telecaller_lead_permissions")]

    operations = [migrations.RunPython(add_expense_permissions, migrations.RunPython.noop)]
