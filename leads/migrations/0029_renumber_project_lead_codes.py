import uuid

from django.db import migrations


def _temporary_code(project_id, lead_id):
    return f"__p4_renumber_{project_id}_{lead_id}_{uuid.uuid4().hex}__"


def renumber_project_lead_codes(apps, schema_editor):
    Project = apps.get_model("inventory", "Project")
    Lead = apps.get_model("leads", "Lead")
    LeadCodeSequence = apps.get_model("leads", "LeadCodeSequence")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    for project in Project.objects.all().order_by("id"):
        leads = list(
            Lead.objects.filter(project_id=project.pk)
            .order_by("created_at", "id")
        )
        if leads:
            renumbered = []
            existing_codes = set(
                Lead.objects.filter(project_id=project.pk).values_list("lead_code", flat=True)
            )
            temporary_codes = set()
            for position, lead in enumerate(leads, start=1):
                new_code = f"{project.code}-L-{position:06d}"
                renumbered.append((lead, lead.lead_code, new_code))

            for lead, _old_code, _new_code in renumbered:
                temporary_code = _temporary_code(project.pk, lead.pk)
                while temporary_code in existing_codes or temporary_code in temporary_codes:
                    temporary_code = _temporary_code(project.pk, lead.pk)
                temporary_codes.add(temporary_code)
                Lead.objects.filter(pk=lead.pk).update(
                    lead_code=temporary_code
                )

            for lead, _old_code, new_code in renumbered:
                Lead.objects.filter(pk=lead.pk).update(lead_code=new_code)

            code_changes = {
                str(lead.pk): {"old": old_code, "new": new_code}
                for lead, old_code, new_code in renumbered
            }
            lead_ids = [str(lead.pk) for lead, _old_code, _new_code in renumbered]
            AuditLog.objects.create(
                organization_id=project.organization_id,
                project_id=project.pk,
                module="leads",
                action="bulk_update",
                method="MIGRATION",
                route="migration:leads.0029_renumber_project_lead_codes",
                details={"lead_codes": code_changes},
                payload_before={"lead_codes": {lead_id: changes["old"] for lead_id, changes in code_changes.items()}},
                payload_after={"lead_codes": {lead_id: changes["new"] for lead_id, changes in code_changes.items()}},
                target_type="Lead",
                target_id=",".join(lead_ids),
            )

        LeadCodeSequence.objects.update_or_create(
            project_id=project.pk,
            defaults={"next_number": len(leads) + 1},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0028_backfill_missing_lead_status"),
    ]

    operations = [
        migrations.RunPython(renumber_project_lead_codes, migrations.RunPython.noop),
    ]
