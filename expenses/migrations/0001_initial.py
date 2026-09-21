from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import expenses.models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0010_expense_permissions"),
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
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ("description", models.TextField()),
                ("payment_method", models.CharField(choices=[("cash", "Cash"), ("card", "Card"), ("bank_transfer", "Bank Transfer"), ("upi", "UPI")], max_length=20)),
                ("receipt", models.FileField(blank=True, null=True, upload_to=expenses.models.receipt_upload_path, validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "pdf"]), expenses.models.validate_receipt_size])),
                ("notes", models.TextField(blank=True)),
                ("project_reference", models.CharField(blank=True, max_length=255)),
                ("is_advance", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("pending_approval", "Pending approval"), ("changes_requested", "Changes requested"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], default="draft", max_length=24)),
                ("payment_status", models.CharField(choices=[("unpaid", "Unpaid"), ("paid", "Paid")], default="unpaid", max_length=12)),
                ("is_deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="expenses.expensecategory")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="organizations.organization")),
                ("paid_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses_paid_fronted", to=settings.AUTH_USER_MODEL)),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses_submitted", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="ApprovalStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step_name", models.CharField(max_length=80)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("done", "Done"), ("rejected", "Rejected")], default="pending", max_length=12)),
                ("acted_at", models.DateTimeField(blank=True, null=True)),
                ("comment", models.TextField(blank=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expense_approval_steps", to=settings.AUTH_USER_MODEL)),
                ("expense", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="approval_steps", to="expenses.expense")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_status", models.CharField(choices=[("unpaid", "Unpaid"), ("paid", "Paid")], default="unpaid", max_length=12)),
                ("payment_date", models.DateField(blank=True, null=True)),
                ("reference_no", models.CharField(blank=True, max_length=100)),
                ("paid_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("expense", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payment", to="expenses.expense")),
                ("paid_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expense_payments_processed", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ReimbursementRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=12)),
                ("requested_on", models.DateTimeField(auto_now_add=True)),
                ("resolved_on", models.DateTimeField(blank=True, null=True)),
                ("advance_adjusted_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expense_reimbursement_requests", to=settings.AUTH_USER_MODEL)),
                ("expense", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reimbursement_requests", to="expenses.expense")),
            ],
        ),
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=32)),
                ("action_date", models.DateTimeField(auto_now_add=True)),
                ("snapshot", models.JSONField(default=dict)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expense_activity_logs", to=settings.AUTH_USER_MODEL)),
                ("expense", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to="expenses.expense")),
            ],
            options={"ordering": ["-action_date", "-id"]},
        ),
        migrations.AddConstraint(model_name="expensecategory", constraint=models.UniqueConstraint(fields=("organization", "name"), name="expenses_category_org_name_unique")),
        migrations.AddIndex(model_name="expense", index=models.Index(fields=["organization", "status"], name="expenses_ex_organiz_9e8b9f_idx")),
        migrations.AddIndex(model_name="expense", index=models.Index(fields=["organization", "payment_status"], name="expenses_ex_organiz_3a0e4e_idx")),
        migrations.AddIndex(model_name="expense", index=models.Index(fields=["organization", "is_deleted"], name="expenses_ex_organiz_7c3d6b_idx")),
    ]
