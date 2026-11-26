from django.db import migrations


def add_uat_self_service_permissions(apps, schema_editor):
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    Permission = apps.get_model("organizations", "Permission")

    role_permissions = {
        "manager": {
            "expenses": {"view_own", "edit_own", "submit"},
        },
        "telecaller": {
            "attendance": {"view", "add", "edit"},
            "leave": {"view", "add", "edit"},
        },
        "site-visit-executive": {
            "attendance": {"view", "add", "edit"},
            "leave": {"view", "add", "edit"},
        },
        "accounts": {
            "attendance": {"view", "add", "edit"},
            "leave": {"view", "add", "edit"},
        },
    }
    for role in OrganizationRole.objects.all():
        additions = role_permissions.get(role.code, {})
        permission_ids = []
        for module, actions in additions.items():
            permission_ids.extend(
                Permission.objects.filter(module=module, action__in=actions).values_list("id", flat=True)
            )
        if permission_ids:
            role.permissions.add(*permission_ids)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0033_uat_d12_employee_mobile")]

    operations = [migrations.RunPython(add_uat_self_service_permissions, migrations.RunPython.noop)]
