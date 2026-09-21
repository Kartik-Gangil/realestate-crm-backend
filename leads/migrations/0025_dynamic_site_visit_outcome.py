from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0024_dynamic_lead_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitevisit",
            name="outcome",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
