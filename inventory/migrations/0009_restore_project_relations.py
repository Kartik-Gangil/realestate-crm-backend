from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_restore_project_context")]

    operations = [
        migrations.AddField(
            model_name="block",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="blocks",
                to="inventory.project",
            ),
        ),
        migrations.AddField(
            model_name="plot",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="plots",
                to="inventory.project",
            ),
        ),
    ]
