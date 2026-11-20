from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Customer, PlotBooking
from inventory.services import _customer_for_booking


class Command(BaseCommand):
    help = "Back-fill the minimal Phase 9 customer table from bookings."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print counts only; do not write personal data.")
        parser.add_argument("--apply", action="store_true", help="Apply the back-fill.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apply_changes = options["apply"]
        if dry_run == apply_changes:
            raise SystemExit("Choose exactly one of --dry-run or --apply.")

        bookings = PlotBooking.objects.select_related("organization", "project", "lead", "plot")
        missing = bookings.filter(customer__isnull=True)
        status_counts = {status: bookings.filter(status=status).count() for status, _label in PlotBooking.Status.choices}
        self.stdout.write(f"bookings_total={bookings.count()}")
        self.stdout.write(f"customers_missing={missing.count()}")
        for status, count in sorted(status_counts.items()):
            self.stdout.write(f"booking_status_{status}={count}")
        if dry_run:
            self.stdout.write("mode=dry-run")
            return

        created = 0
        with transaction.atomic():
            for booking in missing.iterator():
                customer = _customer_for_booking(
                    organization=booking.organization,
                    project=booking.project or booking.plot.project,
                    lead=booking.lead,
                )
                booking.customer = customer
                if booking.project_id is None:
                    booking.project_id = booking.plot.project_id
                booking.save(update_fields=["customer", "project", "updated_at"])
                created += 1
        self.stdout.write(f"customers_created={created}")
        self.stdout.write("mode=apply")
