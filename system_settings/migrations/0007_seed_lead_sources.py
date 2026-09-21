from django.db import migrations


LEAD_SOURCES = (
    ("fb", "Facebook"),
    ("ig", "Instagram"),
    ("website", "Website"),
    ("site_visit", "Site Visit"),
    ("other", "Other"),
    ("walk_in", "Walk-in"),
)


def seed_lead_sources(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Project = apps.get_model("organizations", "Project")
    MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
    MasterData = apps.get_model("system_settings", "MasterData")

    scopes = [(organization.id, None) for organization in Organization.objects.all()]
    scopes.extend(Project.objects.values_list("organization_id", "id"))
    for organization_id, project_id in scopes:
        category, _ = MasterDataCategory.objects.get_or_create(
            organization_id=organization_id,
            project_id=project_id,
            code="lead_source",
            defaults={"name": "Lead Source"},
        )
        for sort_order, (code, name) in enumerate(LEAD_SOURCES, start=1):
            MasterData.objects.get_or_create(
                organization_id=organization_id,
                project_id=project_id,
                category_id=category.id,
                master_type="lead_source",
                code=code,
                defaults={
                    "name": name,
                    "sort_order": sort_order,
                    "is_system": True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0013_project_scope_hr_records"),
        ("system_settings", "0006_systemparameter_float_type"),
    ]

    operations = [
        migrations.RunPython(seed_lead_sources, migrations.RunPython.noop),
    ]
