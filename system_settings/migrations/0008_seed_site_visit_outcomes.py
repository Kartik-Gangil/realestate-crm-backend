from django.db import migrations


SITE_VISIT_OUTCOMES = (
    ("interested", "Interested"),
    ("need_more_time", "Need More Time"),
    ("price_issue", "Price Issue"),
    ("location_issue", "Location Issue"),
    ("loan_issue", "Loan Issue"),
    ("already_purchased", "Already Purchased"),
    ("wrong_requirement", "Wrong Requirement"),
)


def seed_site_visit_outcomes(apps, schema_editor):
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
            code="site_visit_outcome",
            defaults={"name": "Site Visit Outcome"},
        )
        for sort_order, (code, name) in enumerate(SITE_VISIT_OUTCOMES, start=1):
            MasterData.objects.get_or_create(
                organization_id=organization_id,
                project_id=project_id,
                category_id=category.id,
                master_type="site_visit_outcome",
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
        ("system_settings", "0007_seed_lead_sources"),
    ]

    operations = [
        migrations.RunPython(seed_site_visit_outcomes, migrations.RunPython.noop),
    ]
