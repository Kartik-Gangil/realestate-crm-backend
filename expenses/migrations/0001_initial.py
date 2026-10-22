from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("organizations", "0009_payment_registry_permissions"),
        ("inventory", "0009_restore_project_relations"),
    ]
    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expense_categories", to="organizations.organization")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="expense_categories", to="inventory.project")),
            ],
            options={
                "ordering": ["name", "id"],
                "constraints": [models.UniqueConstraint(fields=("organization", "project", "name"), name="expenses_category_org_project_name_unique")],
            },
        ),
    ]
