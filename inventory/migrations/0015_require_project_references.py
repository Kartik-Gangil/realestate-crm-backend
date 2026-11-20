from django.db import migrations, models
import django.db.models.deletion


def fail_if_projectless(apps, schema_editor):
    for model_name in ("Block", "Plot"):
        model = apps.get_model("inventory", model_name)
        if model.objects.filter(project__isnull=True).exists():
            raise RuntimeError(f"Cannot require project on inventory.{model_name}: projectless rows remain.")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0014_rename_inventory_a_agreement_5b4f48_idx_inventory_a_agreeme_1b2581_idx_and_more")]

    operations = [
        migrations.RunPython(fail_if_projectless, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="block", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="blocks", to="inventory.project"),
        ),
        migrations.AlterField(
            model_name="plot", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plots", to="inventory.project"),
        ),
    ]
