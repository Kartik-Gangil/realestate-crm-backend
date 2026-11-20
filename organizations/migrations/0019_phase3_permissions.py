from django.db import migrations, models


ORGANIZATION_MODULES = {"employee", "employees", "role", "attendance", "leave", "settings"}
STANDARD_ACTIONS = ("view", "add", "edit", "delete", "export", "approve")


def _targets(module, action):
    if module == "employee":
        module = "employees"
    if action == "create":
        return [(module, "add")]
    if action == "update":
        return [(module, "edit")]
    if action == "manage":
        if module == "role":
            return [(module, item) for item in ("view", "add", "edit", "delete")]
        return [(module, "edit")]
    return [(module, action)]


def normalize_legacy_permissions(Permission, OrganizationRole):
    legacy = list(Permission.objects.filter(
        models.Q(module="employee") | models.Q(action__in=["create", "update", "manage"])
    ))
    for old_permission in legacy:
        target_permissions = []
        for module, action in _targets(old_permission.module, old_permission.action):
            target, _ = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={
                    "name": f"{action.title()} {module.replace('_', ' ').title()}",
                    "scope": "organization" if module in ORGANIZATION_MODULES else "project",
                },
            )
            target_permissions.append(target)
        for role in OrganizationRole.objects.filter(permissions=old_permission):
            role.permissions.add(*target_permissions)
        old_permission.delete()

    Permission.objects.filter(module__in=ORGANIZATION_MODULES).update(scope="organization")
    Permission.objects.exclude(module__in=ORGANIZATION_MODULES).update(scope="project")
    for role in OrganizationRole.objects.filter(code="admin"):
        role.permissions.set(Permission.objects.all())


def normalize_legacy_permissions_migration(apps, schema_editor):
    normalize_legacy_permissions(
        apps.get_model("organizations", "Permission"),
        apps.get_model("organizations", "OrganizationRole"),
    )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0018_backfill_project_assignments")]

    operations = [
        migrations.AddField(
            model_name="permission",
            name="scope",
            field=models.CharField(
                choices=[("organization", "Organization"), ("project", "Project")],
                default="project",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="organizationrole",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(normalize_legacy_permissions_migration, migrations.RunPython.noop),
    ]
