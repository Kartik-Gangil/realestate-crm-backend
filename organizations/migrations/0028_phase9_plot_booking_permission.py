from django.db import migrations


def seed_plot_booking_permission(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    booking, _ = Permission.objects.get_or_create(
        module="plots",
        action="book",
        defaults={"name": "Create plot booking", "scope": "project"},
    )
    hold, _ = Permission.objects.get_or_create(
        module="plots",
        action="hold",
        defaults={"name": "Request plot hold", "scope": "project"},
    )
    for role in OrganizationRole.objects.filter(code__in=["manager", "telecaller", "site-visit-executive"]):
        role.permissions.add(booking)
        if role.code == "site-visit-executive":
            role.permissions.add(hold)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0027_phase8_plot_hold_permission")]
    operations = [migrations.RunPython(seed_plot_booking_permission, migrations.RunPython.noop)]
