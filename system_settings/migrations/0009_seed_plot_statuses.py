from django.db import migrations


PLOT_STATUSES = (
    ("available", "Available"),
    ("blocked", "Blocked"),
    ("hold", "Hold"),
    ("booked", "Booked"),
    ("sold", "Sold"),
    ("cancelled", "Cancelled"),
    ("under_construction", "Under Construction"),
)


def seed_plot_statuses(apps, schema_editor):
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
            code="plot_status",
            defaults={"name": "Plot Status"},
        )
        for sort_order, (code, name) in enumerate(PLOT_STATUSES, start=1):
            MasterData.objects.get_or_create(
                organization_id=organization_id,
                project_id=project_id,
                category_id=category.id,
                master_type="plot_status",
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
        ("system_settings", "0008_seed_site_visit_outcomes"),
    ]

    operations = [
        migrations.RunPython(seed_plot_statuses, migrations.RunPython.noop),
    ]
