from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0030_phase5_lifecycle_history_and_tags")]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="lifecycle_status",
            field=models.CharField(blank=True, default="new", max_length=32, null=True),
        ),
    ]
