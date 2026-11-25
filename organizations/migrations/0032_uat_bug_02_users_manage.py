from django.db import migrations


def provision_users_manage(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    permission, _ = Permission.objects.get_or_create(
        module="users",
        action="manage",
        defaults={
            "name": "Manage Users",
            "scope": "organization",
        },
    )
    for role in OrganizationRole.objects.filter(code__in=["admin", "hr-admin"]):
        role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0031_alter_leavebalance_options_and_more")]

    operations = [migrations.RunPython(provision_users_manage, migrations.RunPython.noop)]
