from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from expenses.models import Expense, Payment


class Command(BaseCommand):
    help = "Migrate approved-and-paid expenses to Reimbursed while preserving payment references."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        queryset = Expense.objects.filter(status=Expense.Status.APPROVED, payment_status=Expense.PaymentStatus.PAID)
        count = queryset.count()
        self.stdout.write(f"approved_paid_rows={count}")
        if options["dry_run"]:
            self.stdout.write("dry_run=true")
            return
        with transaction.atomic():
            for expense in queryset.select_for_update().iterator():
                payment = Payment.objects.filter(expense=expense).first()
                expense.status = Expense.Status.REIMBURSED
                expense.reimbursement_reference = payment.reference_no if payment else ""
                expense.reimbursed_by_id = payment.paid_by_id if payment else None
                expense.reimbursed_at = payment.created_at if payment else timezone.now()
                expense.save(update_fields=["status", "reimbursement_reference", "reimbursed_by", "reimbursed_at", "updated_at"])
        self.stdout.write(f"migrated={count}")

