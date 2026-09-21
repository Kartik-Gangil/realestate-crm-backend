from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("expenses", "0004_expense_project_expensecategory_project")]

    operations = [
        migrations.RemoveConstraint(
            model_name="expensecategory", name="expenses_category_org_name_unique"
        ),
        migrations.AddConstraint(
            model_name="expensecategory",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "name"),
                name="expenses_category_org_name_unique",
            ),
        ),
    ]
