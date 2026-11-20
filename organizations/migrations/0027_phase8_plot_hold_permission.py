from django.db import migrations


def seed_plot_hold_permission(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    permission, _ = Permission.objects.get_or_create(
        module="plots",
        action="hold",
        defaults={"name": "Request plot hold", "scope": "project"},
    )
    for role in OrganizationRole.objects.filter(code="site-visit-executive"):
        role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0026_site_visit_executive_role")]
    operations = [migrations.RunPython(seed_plot_hold_permission, migrations.RunPython.noop)]
