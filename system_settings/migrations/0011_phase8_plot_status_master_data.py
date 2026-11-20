from django.db import migrations


PLOT_STATUSES = (
    ("available", "Available", "#22C55E"),
    ("hold", "Hold", "#F97316"),
    ("blocked", "Blocked", "#EF4444"),
    ("booked", "Booked", "#A855F7"),
    ("sold", "Sold", "#166534"),
    ("under_construction", "Under Construction", "#9CA3AF"),
    ("cancelled", "Cancelled", "#4B5563"),
)


def seed_plot_statuses(apps, schema_editor):
    MasterData = apps.get_model("system_settings", "MasterData")
    MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
    Project = apps.get_model("inventory", "Project")
    category, _ = MasterDataCategory.objects.get_or_create(code="plot_status", defaults={"name": "Plot status", "is_system": True})
    for project in Project.objects.all().iterator():
        for order, (code, name, color) in enumerate(PLOT_STATUSES):
            MasterData.objects.get_or_create(
                organization_id=project.organization_id,
                project_id=project.pk,
                category_id=category.pk,
                code=code,
                defaults={"name": name, "color": color, "sort_order": order, "is_system": True, "properties": {"lifecycle": True}},
            )


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0010_plot_hold_hours"), ("inventory", "0018_rename_customer_index")]
    operations = [migrations.RunPython(seed_plot_statuses, migrations.RunPython.noop)]
