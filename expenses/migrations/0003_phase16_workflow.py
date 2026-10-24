from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0002_expense"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="expense",
            name="rejection_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["organization", "project", "status"], name="expenses_org_proj_status_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["organization", "project", "payment_status"], name="expenses_org_proj_pay_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["organization", "project", "is_deleted"], name="expenses_org_proj_del_idx"),
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
                ("payment_status", models.CharField(choices=[("unpaid", "Unpaid"), ("paid", "Paid")], default="paid", max_length=12)),
                ("payment_method", models.CharField(choices=[("cash", "Cash"), ("card", "Card"), ("bank_transfer", "Bank Transfer"), ("upi", "UPI")], max_length=32)),
                ("payment_date", models.DateField(blank=True, null=True)),
                ("reference_no", models.CharField(blank=True, max_length=100)),
                ("paid_amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[MinValueValidator(0)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expense", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payment", to="expenses.expense")),
                ("paid_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expense_payments_processed", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ReimbursementRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[MinValueValidator(0.01)])),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=12)),
                ("requested_on", models.DateTimeField(auto_now_add=True)),
                ("resolved_on", models.DateTimeField(blank=True, null=True)),
                ("advance_adjusted_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[MinValueValidator(0)])),
                ("transaction_reference", models.CharField(blank=True, max_length=100)),
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
                ("details", models.JSONField(blank=True, default=dict)),
                ("snapshot", models.JSONField(default=dict)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expense_activity_logs", to=settings.AUTH_USER_MODEL)),
                ("expense", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activity_logs", to="expenses.expense")),
            ],
            options={"ordering": ["-action_date", "-id"]},
        ),
    ]
