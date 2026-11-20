from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_approved_paid(apps, schema_editor):
    Expense = apps.get_model("expenses", "Expense")
    Payment = apps.get_model("expenses", "Payment")
    now = __import__("django.utils.timezone", fromlist=["now"]).now()
    for expense in Expense.objects.filter(status="approved", payment_status="paid").iterator():
        payment = Payment.objects.filter(expense_id=expense.pk).first()
        expense.status = "reimbursed"
        expense.reimbursement_reference = payment.reference_no if payment else ""
        expense.reimbursed_by_id = payment.paid_by_id if payment else None
        expense.reimbursed_at = payment.created_at if payment else now()
        expense.save(update_fields=["status", "reimbursement_reference", "reimbursed_by", "reimbursed_at", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0005_require_project_reference"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name="expense",
            name="reimbursement_reference",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="expense",
            name="reimbursed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="expense",
            name="reimbursed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reimbursed_expenses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(migrate_approved_paid, migrations.RunPython.noop),
    ]

