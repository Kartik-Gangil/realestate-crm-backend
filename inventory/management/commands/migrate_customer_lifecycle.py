from django.core.management.base import BaseCommand

from inventory.customer_services import advance_customer_lifecycle
from inventory.models import Customer, Payment, PlotBooking


class Command(BaseCommand):
    help = "Migrate existing customer lifecycle statuses from bookings and payments."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["dry_run"] == options["apply"]:
            raise SystemExit("Choose exactly one of --dry-run or --apply.")
        counts = {status: 0 for status in ("new", "active", "engaged", "converted")}
        changes = []
        for customer in Customer.objects.all().iterator():
            booking_statuses = set(customer.bookings.values_list("status", flat=True))
            has_successful_payment = Payment.objects.filter(
                booking__customer=customer, status=Payment.Status.SUCCESS
            ).exists()
            if PlotBooking.Status.CONFIRMED in booking_statuses:
                target = Customer.Status.CONVERTED
            elif has_successful_payment:
                target = Customer.Status.ENGAGED
            elif booking_statuses:
                target = Customer.Status.ACTIVE
            else:
                target = Customer.Status.NEW
            counts[target] += 1
            if target != customer.status and target in {Customer.Status.ACTIVE, Customer.Status.ENGAGED, Customer.Status.CONVERTED}:
                changes.append((customer, target))
        self.stdout.write(f"customers_scanned={sum(counts.values())}")
        self.stdout.write(f"changes_total={len(changes)}")
        self.stdout.write(f"target_new={counts['new']}")
        self.stdout.write(f"target_active={counts['active']}")
        self.stdout.write(f"target_engaged={counts['engaged']}")
        self.stdout.write(f"target_converted={counts['converted']}")
        if options["dry_run"]:
            self.stdout.write("mode=dry-run")
            return
        for customer, target in changes:
            advance_customer_lifecycle(
                customer, target, reason="Migrated from existing bookings and payments"
            )
        self.stdout.write(f"changes_applied={len(changes)}")
        self.stdout.write("mode=apply")
