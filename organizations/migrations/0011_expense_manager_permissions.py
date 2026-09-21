from django.db import migrations


def add_manager_expense_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    Role = apps.get_model("organizations", "OrganizationRole")
    permissions = Permission.objects.filter(module="expenses", action__in=["view_team", "approve"])
    for role in Role.objects.filter(code="manager"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0010_expense_permissions")]
    operations = [migrations.RunPython(add_manager_expense_permissions, migrations.RunPython.noop)]
