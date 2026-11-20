from django.db import migrations, models
import django.db.models.deletion


def fail_if_projectless(apps, schema_editor):
    Expense = apps.get_model("expenses", "Expense")
    if Expense.objects.filter(project__isnull=True).exists():
        raise RuntimeError("Cannot require project on expenses.Expense: projectless rows remain.")


class Migration(migrations.Migration):
    dependencies = [("expenses", "0004_expense_choices")]

    operations = [
        migrations.RunPython(fail_if_projectless, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="expense", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="inventory.project"),
        ),
    ]
