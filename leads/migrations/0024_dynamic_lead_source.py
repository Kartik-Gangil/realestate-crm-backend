from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0023_followupcall_project_followupreminder_project_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="source",
            field=models.CharField(default="website", max_length=64),
        ),
    ]
