from django.core.management.base import BaseCommand

from expenses.models import ExpenseCategory
from organizations.models import Organization


DEFAULT_CATEGORIES = ("Travel", "Marketing", "Office Supplies", "Utilities", "Others")


class Command(BaseCommand):
    help = "Create the default expense categories for one or all organizations."

    def add_arguments(self, parser):
        parser.add_argument("--organization", dest="organization_slug", help="Only seed this organization slug.")

    def handle(self, *args, **options):
        organizations = Organization.objects.filter(is_active=True)
        if options.get("organization_slug"):
            organizations = organizations.filter(slug=options["organization_slug"])
        created = 0
        for organization in organizations:
            for name in DEFAULT_CATEGORIES:
                _, was_created = ExpenseCategory.objects.get_or_create(organization=organization, name=name)
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} expense categories."))
