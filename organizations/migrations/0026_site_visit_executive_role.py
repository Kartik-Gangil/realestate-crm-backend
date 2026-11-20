from django.db import migrations


SITE_VISIT_EXECUTIVE_PERMISSIONS = (
    ("site_visits", "view", "View site visits"),
    ("site_visits", "add", "Add site visits"),
    ("site_visits", "edit", "Edit site visits"),
    ("plots", "view", "View plots"),
    ("leads", "view", "View leads"),
)


def migrate_site_visit_executive_roles(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    Permission = apps.get_model("organizations", "Permission")

    permissions = []
    for module, action, name in SITE_VISIT_EXECUTIVE_PERMISSIONS:
        permission, _ = Permission.objects.get_or_create(
            module=module,
            action=action,
            defaults={"name": name, "scope": "project"},
        )
        permissions.append(permission)

    for organization in Organization.objects.all().iterator():
        role, created = OrganizationRole.objects.get_or_create(
            organization=organization,
            code="site-visit-executive",
            defaults={
                "name": "Site Visit Executive",
                "is_system": False,
                "description": "Site-visit executive starting role.",
            },
        )
        if created:
            role.permissions.set(permissions)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0025_phase4_lead_permissions")]

    operations = [
        migrations.RunPython(migrate_site_visit_executive_roles, migrations.RunPython.noop),
    ]
