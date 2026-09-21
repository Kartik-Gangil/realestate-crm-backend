import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0003_payment_method"),
        ("organizations", "0012_organization_code_organization_status_project"),
    ]

    operations = [
        migrations.AddField(
            model_name=model_name,
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_records",
                to="organizations.project",
            ),
        )
        for model_name in ("expense", "expensecategory")
    ]
