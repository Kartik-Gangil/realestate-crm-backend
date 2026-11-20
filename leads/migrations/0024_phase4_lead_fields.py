from django.db import migrations, models
import django.db.models.deletion


STAGES = (
    ("new", "New"),
    ("contacted", "Contacted"),
    ("qualified", "Qualified"),
    ("site_visit", "Site Visit"),
    ("negotiation", "Negotiation"),
    ("won", "Won"),
    ("lost", "Lost"),
)
SOURCES = (
    ("fb", "Facebook"),
    ("ig", "Instagram"),
    ("website", "Website"),
    ("site_visit", "Site Visit"),
    ("walk_in", "Walk-in"),
    ("other", "Other"),
    ("google", "Google"),
)
LEGACY_SOURCE_MAP = {
    "facebook": "fb",
    "instagram": "ig",
    "social_media": "fb",
    "portal": "website",
    "phone": "other",
    "referral": "other",
}


def normalize_phone(value):
    raw = str(value or "").strip()
    compact = "".join(character for character in raw if character.isdigit() or character == "+")
    if compact.startswith("+"):
        digits = compact[1:]
        if digits.startswith("91") and len(digits) == 12:
            return "+91" + digits[2:]
        if 7 <= len(digits) <= 15:
            return "+" + digits
        return None
    digits = "".join(character for character in compact if character.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        return "+91" + digits[-10:]
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    return None


def seed_lead_master_data(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Project = apps.get_model("inventory", "Project")
    MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
    MasterData = apps.get_model("system_settings", "MasterData")
    for organization in Organization.objects.all():
        stage_category, _ = MasterDataCategory.objects.get_or_create(
            code="lead_stage", defaults={"name": "Lead stage", "is_system": True}
        )
        source_category, _ = MasterDataCategory.objects.get_or_create(
            code="lead_source", defaults={"name": "Lead source", "is_system": True}
        )
        for category, values in ((stage_category, STAGES), (source_category, SOURCES)):
            for sort_order, (code, name) in enumerate(values):
                MasterData.objects.get_or_create(
                    organization_id=organization.pk,
                    project_id=None,
                    category_id=category.pk,
                    code=code,
                    defaults={"name": name, "is_system": True, "sort_order": sort_order},
                )
        for project in Project.objects.filter(organization_id=organization.pk):
            for default in MasterData.objects.filter(organization_id=organization.pk, project_id=None):
                MasterData.objects.get_or_create(
                    organization_id=organization.pk,
                    project_id=project.pk,
                    category_id=default.category_id,
                    code=default.code,
                    defaults={
                        "name": default.name,
                        "color": default.color,
                        "description": default.description,
                        "properties": default.properties,
                        "is_active": default.is_active,
                        "is_system": default.is_system,
                        "sort_order": default.sort_order,
                    },
                )


def backfill_leads(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    FollowUpCall = apps.get_model("leads", "FollowUpCall")
    LeadCodeSequence = apps.get_model("leads", "LeadCodeSequence")
    MasterData = apps.get_model("system_settings", "MasterData")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    for lead in Lead.objects.select_related("project").order_by("project_id", "created_at", "id"):
        source_code = LEGACY_SOURCE_MAP.get(lead.source, lead.source or "website")
        source_item = MasterData.objects.filter(
            organization_id=lead.organization_id,
            project_id=lead.project_id,
            category__code="lead_source",
            code=source_code,
        ).first()
        latest_status = FollowUpCall.objects.filter(lead_id=lead.pk).order_by("-created_at", "-id").values_list("status", flat=True).first() or "new"
        status_item = MasterData.objects.filter(
            organization_id=lead.organization_id,
            project_id=lead.project_id,
            category__code="lead_stage",
            code=latest_status,
        ).first()
        code = lead.lead_code or f"{lead.project.code}-L-{lead.pk:06d}"
        normalized = normalize_phone(lead.phone)
        before = {"lead_code": lead.lead_code, "source": lead.source, "status": None, "phone_normalized": False}
        updates = {
            "lead_code": code,
            "source_item_id": source_item.pk if source_item else None,
            "status_id": status_item.pk if status_item else None,
        }
        if normalized:
            updates["phone"] = normalized
            before["phone_normalized"] = True
        Lead.objects.filter(pk=lead.pk).update(**updates)
        AuditLog.objects.create(
            organization_id=lead.organization_id,
            project_id=lead.project_id,
            module="leads",
            action="phase4_migration_backfill",
            method="MIGRATION",
            route="migration:leads.0024_phase4_lead_fields",
            details={"fields": ["lead_code", "source_item", "status", "phone"]},
            payload_before=before,
            payload_after={"lead_code": code, "source": source_code, "status": latest_status},
            target_type="Lead",
            target_id=str(lead.pk),
        )

    for project in apps.get_model("inventory", "Project").objects.all():
        codes = list(Lead.objects.filter(project_id=project.pk).values_list("lead_code", flat=True))
        maximum = 0
        for code in codes:
            try:
                maximum = max(maximum, int(str(code).rsplit("-", 1)[-1]))
            except (TypeError, ValueError):
                continue
        LeadCodeSequence.objects.update_or_create(
            project_id=project.pk,
            defaults={"next_number": maximum + 1},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0023_require_project_references"),
        ("system_settings", "0006_alter_auditlog_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeadCodeSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_number", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="lead_code_sequence", to="inventory.project")),
            ],
        ),
        migrations.AddField(model_name="lead", name="lead_code", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="lead", name="source_item", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="lead_source_items", to="system_settings.masterdata")),
        migrations.AddField(model_name="lead", name="status", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="lead_status_items", to="system_settings.masterdata")),
        migrations.AddField(model_name="lead", name="score", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="lead", name="budget_range", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="lead", name="preferred_location", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="lead", name="external_source", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField(model_name="lead", name="external_id", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddConstraint(
            model_name="lead",
            constraint=models.UniqueConstraint(condition=~models.Q(("lead_code", "")), fields=("project", "lead_code"), name="leads_project_lead_code_unique"),
        ),
        migrations.AddConstraint(
            model_name="lead",
            constraint=models.UniqueConstraint(condition=~models.Q(("external_id", "")), fields=("project", "external_source", "external_id"), name="leads_project_external_id_unique"),
        ),
        migrations.RunPython(seed_lead_master_data, migrations.RunPython.noop),
        migrations.RunPython(backfill_leads, migrations.RunPython.noop),
    ]
