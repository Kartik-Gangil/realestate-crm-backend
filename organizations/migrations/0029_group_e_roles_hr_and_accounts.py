from django.db import migrations


PERMISSIONS = {
    ("employees", "view_compensation"): "View employee compensation",
    ("expenses", "reimburse"): "Reimburse approved expenses",
}


def provision_group_e_roles(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    Permission = apps.get_model("organizations", "Permission")

    for (module, action), name in PERMISSIONS.items():
        Permission.objects.get_or_create(
            module=module,
            action=action,
            defaults={"name": name, "scope": "organization" if module == "employees" else "project"},
        )

    for organization in Organization.objects.all().iterator():
        hr_role, _ = OrganizationRole.objects.get_or_create(
            organization=organization,
            code="hr-admin",
            defaults={"name": "HR Admin", "description": "Human resources administrator"},
        )
        accounts_role, _ = OrganizationRole.objects.get_or_create(
            organization=organization,
            code="accounts",
            defaults={"name": "Accounts", "description": "Expense reimbursement processor"},
        )
        hr_permissions = Permission.objects.filter(
            module__in=["dashboard", "employees", "attendance", "leave"],
            action__in=["view", "view_team", "add", "edit", "manage", "approve", "view_compensation"],
        )
        accounts_permissions = Permission.objects.filter(
            module="expenses",
            action__in=["view", "view_team", "process_reimbursement", "reimburse"],
        )
        hr_role.permissions.set(hr_permissions)
        accounts_role.permissions.set(accounts_permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0028_phase9_plot_booking_permission")]
    operations = [migrations.RunPython(provision_group_e_roles, migrations.RunPython.noop)]

