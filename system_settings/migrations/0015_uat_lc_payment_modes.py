from django.db import migrations


PAYMENT_MODES = (
    ("upi", "UPI"),
    ("card", "Card"),
    ("net_banking", "Net Banking"),
    ("cash", "Cash"),
    ("cheque", "Cheque"),
)


def seed_payment_modes(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Project = apps.get_model("inventory", "Project")
    MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
    MasterData = apps.get_model("system_settings", "MasterData")

    category, _ = MasterDataCategory.objects.get_or_create(
        code="payment_mode",
        defaults={"name": "Payment mode", "is_system": True},
    )
    for organization in Organization.objects.all():
        defaults = []
        for sort_order, (code, name) in enumerate(PAYMENT_MODES):
            default, _ = MasterData.objects.get_or_create(
                organization_id=organization.pk,
                project_id=None,
                category_id=category.pk,
                code=code,
                defaults={"name": name, "is_system": True, "sort_order": sort_order},
            )
            defaults.append(default)
        for project in Project.objects.filter(organization_id=organization.pk):
            for default in defaults:
                MasterData.objects.get_or_create(
                    organization_id=organization.pk,
                    project_id=project.pk,
                    category_id=category.pk,
                    code=default.code,
                    defaults={
                        "name": default.name,
                        "is_system": default.is_system,
                        "sort_order": default.sort_order,
                    },
                )


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0014_uat_d13_support_email"),
    ]

    operations = [migrations.RunPython(seed_payment_modes, migrations.RunPython.noop)]
