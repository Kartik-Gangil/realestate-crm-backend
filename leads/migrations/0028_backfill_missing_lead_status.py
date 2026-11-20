from django.db import migrations


def backfill_missing_lead_status(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    FollowUpCall = apps.get_model("leads", "FollowUpCall")
    MasterData = apps.get_model("system_settings", "MasterData")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    changed_ids = []
    status_changes = {}
    for lead in Lead.objects.filter(status_id__isnull=True).only("id", "organization_id", "project_id"):
        latest_status = (
            FollowUpCall.objects.filter(lead_id=lead.id)
            .order_by("-created_at", "-id")
            .values_list("status", flat=True)
            .first()
        )
        status_code = latest_status or "new"
        status_item = MasterData.objects.filter(
            organization_id=lead.organization_id,
            project_id=lead.project_id,
            category__code="lead_stage",
            code=status_code,
            is_active=True,
        ).first()
        if status_item is None and status_code != "new":
            status_code = "new"
            status_item = MasterData.objects.filter(
                organization_id=lead.organization_id,
                project_id=lead.project_id,
                category__code="lead_stage",
                code="new",
                is_active=True,
            ).first()
        if status_item is None:
            continue
        status_changes.setdefault((lead.project_id, status_code), []).append(lead.id)

    for (project_id, status_code), lead_ids in status_changes.items():
        status_item = MasterData.objects.filter(
            code=status_code,
            category__code="lead_stage",
            project_id=project_id,
            is_active=True,
        ).first()
        if status_item is None:
            continue
        updated = Lead.objects.filter(pk__in=lead_ids, status_id__isnull=True).update(status_id=status_item.id)
        if updated:
            changed_ids.extend(lead_ids)

    if changed_ids:
        AuditLog.objects.create(
            module="leads",
            action="bulk_update",
            method="MIGRATION",
            route="migration:leads.0028_backfill_missing_lead_status",
            details={
                "record_ids": changed_ids,
                "changed_values": {"fields": ["status"]},
            },
            target_type="Lead",
            target_id=",".join(str(lead_id) for lead_id in changed_ids),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0027_alter_lead_source"),
    ]

    operations = [
        migrations.RunPython(backfill_missing_lead_status, migrations.RunPython.noop),
    ]
