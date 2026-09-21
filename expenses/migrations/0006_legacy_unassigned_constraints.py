from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("expenses", "0005_project_scoped_constraints")]
    operations = [
        migrations.AddConstraint(
            model_name="expensecategory",
            constraint=models.UniqueConstraint(fields=("organization", "name"), condition=models.Q(project__isnull=True), name="expenses_category_org_name_legacy"),
        )
    ]
