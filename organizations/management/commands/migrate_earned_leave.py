from django.core.management.base import BaseCommand
from django.db import transaction

from organizations.models import LeaveRequest


class Command(BaseCommand):
    help = "Migrate legacy Earned leave requests to Paid leave."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        queryset = LeaveRequest.objects.filter(leave_type=LeaveRequest.LeaveType.EARNED)
        count = queryset.count()
        self.stdout.write(f"earned_leave_rows={count}")
        if options["dry_run"]:
            self.stdout.write("dry_run=true")
            return
        with transaction.atomic():
            queryset.update(leave_type=LeaveRequest.LeaveType.PAID)
        self.stdout.write(f"migrated={count}")

