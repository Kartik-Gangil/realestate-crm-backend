from django.db import migrations, models
import django.db.models.deletion


CATEGORY_SEEDS = {
    "plot_status": "Plot status",
    "lead_source": "Lead source",
    "lead_stage": "Lead stage",
    "payment_mode": "Payment mode",
    "document_type": "Document type",
    "registry_charge_type": "Registry charge type",
    "expense_category": "Expense category",
}

PARAMETER_SEEDS = (
    ("auto_logout_minutes", "Auto logout minutes", 30, "integer"),
    ("site_visit_max_days_ahead", "Site visit maximum days ahead", 90, "integer"),
    ("booking_hold_days", "Booking hold days", 7, "integer"),
    ("payment_pending_grace_minutes", "Payment pending grace minutes", 15, "integer"),
    ("plot_selection_expiry_minutes", "Plot selection expiry minutes", 30, "integer"),
    ("document_expiry_warning_days", "Document expiry warning days", 30, "integer"),
    ("duplicate_score_phone_exact", "Duplicate score phone exact", 95, "integer"),
    ("duplicate_score_phone_different_name", "Duplicate score phone different name", 90, "integer"),
    ("duplicate_score_email_partial_phone", "Duplicate score email partial phone", 80, "integer"),
    ("expense_receipt_threshold", "Expense receipt threshold", 5000, "decimal"),
)


def seed_categories_and_backfill(apps, schema_editor):
    Category = apps.get_model("system_settings", "MasterDataCategory")
    MasterData = apps.get_model("system_settings", "MasterData")
    for code, name in CATEGORY_SEEDS.items():
        Category.objects.get_or_create(code=code, defaults={"name": name, "is_system": True})
    for master in MasterData.objects.select_related("organization"):
        code = master.master_type or "legacy"
        category, _ = Category.objects.get_or_create(code=code, defaults={"name": code.replace("_", " ").title(), "is_system": True})
        master.category_id = category.pk
        master.save(update_fields=["category"])

    Organization = apps.get_model("organizations", "Organization")
    SystemParameter = apps.get_model("system_settings", "SystemParameter")
    Project = apps.get_model("inventory", "Project")
    for organization in Organization.objects.all():
        for key, name, value, data_type in PARAMETER_SEEDS:
            is_project = key != "auto_logout_minutes"
            if is_project:
                projects = Project.objects.filter(organization_id=organization.pk)
                for project in projects:
                    SystemParameter.objects.get_or_create(
                        organization_id=organization.pk,
                        project_id=project.pk,
                        parameter_key=key,
                        defaults={"parameter_name": name, "value": value, "data_type": data_type},
                    )
            else:
                SystemParameter.objects.get_or_create(
                    organization_id=organization.pk,
                    project_id=None,
                    parameter_key=key,
                    defaults={"parameter_name": name, "value": value, "data_type": data_type},
                )


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0002_remove_masterdata_settings_master_code_unique_and_more"),
        ("inventory", "0015_require_project_references"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterDataCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("is_system", models.BooleanField(default=True)),
            ],
            options={"ordering": ("name", "code")},
        ),
        migrations.AddField(
            model_name="masterdata",
            name="category",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="items", to="system_settings.masterdatacategory"),
        ),
        migrations.AddField(
            model_name="masterdata",
            name="properties",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(seed_categories_and_backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="masterdata",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="system_settings.masterdatacategory"),
        ),
        migrations.RemoveConstraint(model_name="masterdata", name="settings_master_default_code_unique"),
        migrations.RemoveConstraint(model_name="masterdata", name="settings_master_project_code_unique"),
        migrations.RemoveField(model_name="masterdata", name="master_type"),
        migrations.AddConstraint(
            model_name="masterdata",
            constraint=models.UniqueConstraint(condition=models.Q(("project__isnull", True)), fields=("organization", "category", "code"), name="settings_master_default_code_unique"),
        ),
        migrations.AddConstraint(
            model_name="masterdata",
            constraint=models.UniqueConstraint(condition=models.Q(("project__isnull", False)), fields=("organization", "project", "category", "code"), name="settings_master_project_code_unique"),
        ),
    ]
