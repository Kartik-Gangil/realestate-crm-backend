from django.core.management.base import BaseCommand

from expenses.models import ExpenseCategory
from organizations.models import Organization


DEFAULT_CATEGORIES = ("Travel", "Marketing", "Office Supplies", "Utilities", "Others")


class Command(BaseCommand):
    help = "Create the default expense categories for every active organization."

    def handle(self, *args, **options):
        created = 0
        for organization in Organization.objects.filter(is_active=True):
            for name in DEFAULT_CATEGORIES:
                _, was_created = ExpenseCategory.objects.get_or_create(
                    organization=organization,
                    project=None,
                    name=name,
                    defaults={"description": f"{name} expenses"},
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} expense categories."))
