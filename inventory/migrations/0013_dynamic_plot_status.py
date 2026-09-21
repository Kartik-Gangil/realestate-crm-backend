from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0012_legacy_unassigned_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plot",
            name="status",
            field=models.CharField(default="available", max_length=64),
        ),
        migrations.AlterField(
            model_name="plotstatushistory",
            name="old_status",
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name="plotstatushistory",
            name="new_status",
            field=models.CharField(max_length=64),
        ),
    ]
