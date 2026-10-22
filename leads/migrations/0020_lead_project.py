from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0019_phase6_call_recording"), ("inventory", "0008_restore_project_context")]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="project",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="leads", to="inventory.project"),
        ),
    ]
