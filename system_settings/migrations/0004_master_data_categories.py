from django.db import migrations, models
import django.db.models.deletion


def backfill_master_data_categories(apps, schema_editor):
    MasterData = apps.get_model("system_settings", "MasterData")
    MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
    for item in MasterData.objects.all().iterator():
        category, _ = MasterDataCategory.objects.get_or_create(
            organization_id=item.organization_id,
            project_id=item.project_id,
            code=item.master_type,
            defaults={"name": item.master_type.replace("_", " ").title()},
        )
        item.category_id = category.id
        item.save(update_fields=["category"])


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0013_project_scope_hr_records"),
        ("system_settings", "0003_project_scope_settings_records"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterDataCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=40)),
                ("name", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="master_data_categories", to="organizations.organization")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
            ],
            options={"ordering": ("name", "id")},
        ),
        migrations.AddConstraint(
            model_name="masterdatacategory",
            constraint=models.UniqueConstraint(fields=("organization", "project", "code"), name="settings_master_category_code_unique"),
        ),
        migrations.AddConstraint(
            model_name="masterdatacategory",
            constraint=models.UniqueConstraint(condition=models.Q(("project__isnull", True)), fields=("organization", "code"), name="settings_master_category_code_legacy"),
        ),
        migrations.AddField(
            model_name="masterdata",
            name="category",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="items", to="system_settings.masterdatacategory"),
        ),
        migrations.RunPython(backfill_master_data_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="masterdata",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="system_settings.masterdatacategory"),
        ),
    ]
