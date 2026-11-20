from django.db import migrations, transaction


def migrate_manager_roles(apps, schema_editor):
    OrganizationMembership = apps.get_model("organizations", "OrganizationMembership")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    Permission = apps.get_model("organizations", "Permission")
    Project = apps.get_model("inventory", "Project")
    ProjectAssignment = apps.get_model("organizations", "ProjectAssignment")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    with transaction.atomic():
        manager_memberships = OrganizationMembership.objects.filter(
            organization_role__code="manager"
        ).select_related("organization_role", "organization")
        for membership in manager_memberships:
            if ProjectAssignment.objects.filter(membership=membership).exists():
                continue
            for project in Project.objects.filter(organization=membership.organization):
                assignment, created = ProjectAssignment.objects.get_or_create(
                    membership=membership,
                    project=project,
                    defaults={"role": membership.organization_role, "assigned_by": None},
                )
                if created:
                    AuditLog.objects.create(
                        organization=membership.organization,
                        project=project,
                        user=None,
                        module="organizations",
                        action="project_assignment_created",
                        method="COMMAND",
                        route="command:migrate",
                        details={"role": "manager", "project": project.name},
                    )

        settings_edit = Permission.objects.filter(module="settings", action="edit").first()
        if settings_edit is None:
            return
        for role in OrganizationRole.objects.filter(code="manager").select_related("organization"):
            if role.permissions.filter(pk=settings_edit.pk).exists():
                role.permissions.remove(settings_edit)
                AuditLog.objects.create(
                    organization=role.organization,
                    project=None,
                    user=None,
                    module="organizations",
                    action="manager_settings_edit_removed",
                    method="COMMAND",
                    route="command:migrate",
                    details={"role": "manager", "permission": "settings.edit"},
                )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0022_manager_employee_team_view"),
        ("system_settings", "0006_alter_auditlog_options"),
    ]

    operations = [migrations.RunPython(migrate_manager_roles, migrations.RunPython.noop)]
