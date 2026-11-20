from django.db import migrations


def grant_read_only_inventory_view(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")

    plots_view, _ = Permission.objects.get_or_create(
        module="plots",
        action="view",
        defaults={"name": "View plots"},
    )
    plots_view_team, _ = Permission.objects.get_or_create(
        module="plots",
        action="view_team",
        defaults={"name": "View all project plots"},
    )
    mutation_permissions = Permission.objects.filter(module="plots").exclude(
        action__in=["view", "view_team"]
    )
    for role in OrganizationRole.objects.filter(code="telecaller"):
        role.permissions.add(plots_view, plots_view_team)
        role.permissions.remove(*mutation_permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0016_project_assignments")]

    operations = [migrations.RunPython(grant_read_only_inventory_view, migrations.RunPython.noop)]
