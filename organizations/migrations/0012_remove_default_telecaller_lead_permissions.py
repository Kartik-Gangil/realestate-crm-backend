from django.db import migrations


def remove_default_telecaller_lead_permissions(apps, schema_editor):
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    Permission = apps.get_model("organizations", "Permission")
    lead_permissions = Permission.objects.filter(module="leads")

    for role in OrganizationRole.objects.filter(code="telecaller", is_system=True):
        role.permissions.remove(*lead_permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0011_frontend_matrix_permissions")]

    operations = [
        migrations.RunPython(remove_default_telecaller_lead_permissions, migrations.RunPython.noop),
    ]
