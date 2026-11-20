from django.db import migrations


def backfill_assignments(apps, schema_editor):
    Project = apps.get_model("inventory", "Project")
    ProjectAssignment = apps.get_model("organizations", "ProjectAssignment")
    through = Project._meta.get_field("assigned_memberships").remote_field.through
    for link in through.objects.select_related("project", "organizationmembership"):
        membership = link.organizationmembership
        project = link.project
        if project.organization_id != membership.organization_id:
            raise RuntimeError("Cannot backfill a project assignment across organizations.")
        if not membership.organization_role_id:
            raise RuntimeError("Cannot backfill a project assignment without an organization role.")
        ProjectAssignment.objects.get_or_create(
            membership_id=membership.pk,
            project_id=project.pk,
            defaults={"role_id": membership.organization_role_id},
        )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0017_telecaller_inventory_view")]
    operations = [migrations.RunPython(backfill_assignments, migrations.RunPython.noop)]
