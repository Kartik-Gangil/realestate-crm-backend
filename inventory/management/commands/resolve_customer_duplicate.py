from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db import models

from documents.models import CustomerDocument
from inventory.customer_services import (
    _identity_query,
    normalize_customer_email,
    normalize_phone,
)
from inventory.models import Customer, CustomerNote
from system_settings.audit import log_command_audit


class Command(BaseCommand):
    help = "Resolve a customer duplicate without deleting either customer."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=("merge", "correct-phone"))
        parser.add_argument("--keep")
        parser.add_argument("--merge")
        parser.add_argument("--customer")
        parser.add_argument("--phone")
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--dry-run", action="store_true")
        action.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["mode"] == "merge":
            self._merge(options)
        else:
            self._correct_phone(options)

    def _customer(self, code):
        if not code:
            raise CommandError("A customer code is required.")
        try:
            return Customer.objects.select_related("project", "lead").get(customer_code=code)
        except Customer.DoesNotExist as error:
            raise CommandError("Customer code was not found.") from error

    def _merge(self, options):
        kept = self._customer(options.get("keep"))
        merged = self._customer(options.get("merge"))
        if kept.pk == merged.pk or kept.project_id != merged.project_id or kept.organization_id != merged.organization_id:
            raise CommandError("Customers must be different records in the same project and organization.")
        bookings = kept.bookings.filter(pk__in=merged.bookings.values("pk")).count()
        notes = CustomerNote.objects.filter(customer=merged).count()
        documents = CustomerDocument.objects.filter(customer_id=merged.pk).count()
        if options["dry_run"]:
            self.stdout.write(f"bookings_to_move={bookings}")
            self.stdout.write(f"notes_to_move={notes}")
            self.stdout.write(f"documents_to_move={documents}")
            self.stdout.write("mode=dry-run")
            return
        with transaction.atomic():
            old_values = {"phone": merged.phone, "email": merged.email, "status": merged.status}
            moved_bookings = merged.bookings.select_for_update().count()
            for booking in merged.bookings.select_for_update().all():
                booking.customer = kept
                booking.save(update_fields=["customer", "updated_at"])
            for note in CustomerNote.objects.select_for_update().filter(customer=merged).all():
                models.QuerySet.update(CustomerNote.objects.filter(pk=note.pk), customer=kept)
            CustomerDocument.objects.filter(customer_id=merged.pk).update(customer_id=kept.pk)
            merged.status = Customer.Status.INACTIVE
            merged.lifecycle_reason = f"Merged into {kept.customer_code}"
            merged.phone = ""
            merged.email = ""
            merged.government_id_type = ""
            merged.government_id_encrypted = ""
            merged.government_id_hash = ""
            merged.government_id_last4 = ""
            merged.save(update_fields=["status", "lifecycle_reason", "phone", "email", "government_id_type", "government_id_encrypted", "government_id_hash", "government_id_last4", "updated_at"])
            log_command_audit(
                module="customers", action="merge", route="command:resolve_customer_duplicate",
                organization=kept.organization, project=kept.project,
                details={
                    "kept_customer_code": kept.customer_code,
                    "merged_customer_code": merged.customer_code,
                    "old_values": old_values,
                    "bookings_moved": moved_bookings,
                    "notes_moved": notes,
                    "documents_moved": documents,
                },
            )
        self.stdout.write(f"bookings_moved={bookings}")
        self.stdout.write(f"notes_moved={notes}")
        self.stdout.write(f"documents_moved={documents}")
        self.stdout.write("mode=apply")

    def _correct_phone(self, options):
        customer = self._customer(options.get("customer"))
        normalized = normalize_phone(options.get("phone"))
        if normalized is None:
            raise CommandError("Phone number cannot be normalized.")
        duplicate = _identity_query(customer.project, phone=normalized, exclude_id=customer.pk).first()
        if duplicate:
            raise CommandError("The corrected phone already belongs to another customer in this project.")
        changed = int(customer.phone != normalized)
        self.stdout.write(f"would_update={changed}")
        if options["dry_run"]:
            self.stdout.write("mode=dry-run")
            return
        old_phone = customer.phone
        customer.phone = normalized
        customer.save(update_fields=["phone", "updated_at"])
        log_command_audit(
            module="customers", action="correct_phone", route="command:resolve_customer_duplicate",
            organization=customer.organization, project=customer.project,
            details={"customer_code": customer.customer_code, "old_phone": old_phone},
        )
        self.stdout.write(f"updated={changed}")
        self.stdout.write("mode=apply")
