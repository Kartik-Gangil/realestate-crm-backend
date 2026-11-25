from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0034_mark_old_reminders_sent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="source",
            field=models.CharField(default="website", max_length=64),
        ),
    ]
