from django.db import migrations, models
import django.db.models.deletion


def fail_if_projectless(apps, schema_editor):
    for model_name in ("Lead", "Sitevisit"):
        model = apps.get_model("leads", model_name)
        if model.objects.filter(project__isnull=True).exists():
            raise RuntimeError(f"Cannot require project on leads.{model_name}: projectless rows remain.")


class Migration(migrations.Migration):
    dependencies = [("leads", "0022_alter_followupcall_outcome")]

    operations = [
        migrations.RunPython(fail_if_projectless, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lead", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="leads", to="inventory.project"),
        ),
        migrations.AlterField(
            model_name="sitevisit", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="site_visits", to="inventory.project"),
        ),
    ]
