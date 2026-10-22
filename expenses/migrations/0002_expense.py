from django.conf import settings
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import expenses.models


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0001_initial"),
        ("organizations", "0009_payment_registry_permissions"),
        ("inventory", "0009_restore_project_relations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("expense_id", models.CharField(editable=False, max_length=32, unique=True)),
                ("date", models.DateField(default=django.utils.timezone.localdate)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[MinValueValidator(0)])),
                ("description", models.TextField()),
                ("notes", models.TextField(blank=True)),
                ("project_reference", models.CharField(blank=True, max_length=150)),
                ("payment_method", models.CharField(default="cash", max_length=32)),
                ("is_advance", models.BooleanField(default=False)),
                ("receipt", models.FileField(blank=True, null=True, upload_to=expenses.models.receipt_upload_path, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"]), expenses.models.validate_receipt_size])),
                ("status", models.CharField(choices=[("draft", "Draft"), ("pending_approval", "Pending Approval"), ("changes_requested", "Changes Requested"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], default="draft", max_length=24)),
                ("payment_status", models.CharField(default="unpaid", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="expenses.expensecategory")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="organizations.organization")),
                ("paid_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="paid_expenses", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="inventory.project")),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="submitted_expenses", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
