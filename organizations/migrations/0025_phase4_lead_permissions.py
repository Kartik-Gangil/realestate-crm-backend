from django.db import migrations


def add_phase4_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    permissions = {}
    for action, requirement in (("import", "FR-P4-03"), ("sync", "FR-P4-01"), ("add", "FR-P4-06")):
        permission, _ = Permission.objects.get_or_create(
            module="leads",
            action=action,
            defaults={"name": f"{action.title()} Leads", "scope": "project"},
        )
        permissions[action] = permission
    for role in OrganizationRole.objects.filter(code__in=("manager", "telecaller")):
        before = sorted(f"{item.module}.{item.action}" for item in role.permissions.all())
        role.permissions.add(permissions["add"])
        if role.code == "manager":
            role.permissions.add(permissions["import"], permissions["sync"])
        after = sorted(f"{item.module}.{item.action}" for item in role.permissions.all())
        AuditLog.objects.create(
            organization_id=role.organization_id,
            project_id=None,
            user_id=None,
            module="organizations",
            action="phase4_permission_migration",
            method="MIGRATION",
            route="migration:organizations.0025_phase4_lead_permissions",
            details={"role_code": role.code, "requirements": ["FR-P4-01", "FR-P4-03", "FR-P4-06"]},
            payload_before={"permissions": before},
            payload_after={"permissions": after},
            target_type="OrganizationRole",
            target_id=str(role.pk),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0024_remove_unused_permissions"),
        ("system_settings", "0006_alter_auditlog_options"),
    ]

    operations = [migrations.RunPython(add_phase4_permissions, migrations.RunPython.noop)]
