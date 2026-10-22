from django.db import migrations


def add_telecalling_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    telecalling, _ = Permission.objects.get_or_create(
        module="telecalling",
        action="view",
        defaults={"name": "View telecalling"},
    )
    follow_ups, _ = Permission.objects.get_or_create(
        module="follow_ups",
        action="view",
        defaults={"name": "View follow-ups"},
    )

    for role in OrganizationRole.objects.filter(code="telecaller"):
        role.permissions.add(telecalling, follow_ups)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0009_payment_registry_permissions")]

    operations = [migrations.RunPython(add_telecalling_permissions, migrations.RunPython.noop)]
