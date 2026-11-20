from django.core.management.base import BaseCommand
from django.db import transaction

from expenses.models import Expense, ExpenseCategory
from inventory.models import Project

from system_settings.models import MasterData, SystemParameter
from system_settings.services import clone_project_defaults


class Command(BaseCommand):
    help = "Copy organization configuration defaults to existing projects."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")

    def _counts(self, project):
        masters = MasterData.objects.filter(organization=project.organization, project__isnull=True)
        existing_masters = set(MasterData.objects.filter(project=project).values_list("category_id", "code"))
        parameters = SystemParameter.objects.filter(organization=project.organization, project__isnull=True)
        existing_parameters = set(SystemParameter.objects.filter(project=project).values_list("parameter_key", flat=True))
        categories = ExpenseCategory.objects.filter(organization=project.organization, project__isnull=True)
        existing_categories = set(ExpenseCategory.objects.filter(project=project).values_list("name", flat=True))
        category_names = list(categories.values_list("name", flat=True))
        expenses_to_remap = Expense.objects.filter(
            organization=project.organization,
            project=project,
            category__organization=project.organization,
            category__project__isnull=True,
            category__name__in=category_names,
        ).count()
        return {
            "MasterData": sum((item.category_id, item.code) not in existing_masters for item in masters),
            "SystemParameter": sum(item.parameter_key not in existing_parameters for item in parameters),
            "ExpenseCategory": sum(item.name not in existing_categories for item in categories),
            "name_matches_reused": sum(name in existing_categories for name in category_names),
            "expenses_to_remap": expenses_to_remap,
        }

    def handle(self, *args, **options):
        totals = {
            "MasterData": 0,
            "SystemParameter": 0,
            "ExpenseCategory": 0,
            "name_matches_reused": 0,
            "expenses_to_remap": 0,
        }
        for project in Project.objects.select_related("organization").order_by("pk"):
            counts = self._counts(project)
            self.stdout.write(
                f"project={project.code} "
                + " ".join(
                    f"{key}={value}"
                    for key, value in counts.items()
                )
            )
            for key, value in counts.items():
                totals[key] += value
        self.stdout.write("totals " + " ".join(f"{key}={value}" for key, value in totals.items()))
        self.stdout.write(f"dry_run={'true' if options['dry_run'] else 'false'}")
        if options["apply"]:
            with transaction.atomic():
                for project in Project.objects.select_related("organization").order_by("pk"):
                    clone_project_defaults(project)
            self.stdout.write("applied=true")
