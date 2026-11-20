from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from collections import Counter

from expenses.models import Expense
from leads.models import Lead, Sitevisit
from organizations.models import Organization

from inventory.models import Block, Plot, PlotBooking, PlotHold, PlotSelection, Project
from system_settings.audit import log_bulk_audit


def collect_assignment_report(organization):
    projectless_blocks = Block.objects.filter(organization=organization, project__isnull=True)
    projectless_plots = Plot.objects.filter(organization=organization, project__isnull=True)
    plot_ids = list(projectless_plots.values_list("pk", flat=True))
    bookings = PlotBooking.objects.filter(plot_id__in=plot_ids).select_related("lead__project")
    selections = PlotSelection.objects.filter(plot_id__in=plot_ids).select_related("lead__project")
    holds = PlotHold.objects.filter(plot_id__in=plot_ids)
    linked_lead_projects = Counter()
    for lead_project in bookings.values_list("lead__project__code", flat=True):
        linked_lead_projects[lead_project or "none"] += 1
    for lead_project in selections.values_list("lead__project__code", flat=True):
        linked_lead_projects[lead_project or "none"] += 1
    return {
        "counts": {
            "Block": projectless_blocks.count(),
            "Plot": projectless_plots.count(),
            "Lead": Lead.objects.filter(organization=organization, project__isnull=True).count(),
            "Sitevisit": Sitevisit.objects.filter(organization=organization, project__isnull=True).count(),
            "Expense": Expense.objects.filter(organization=organization, project__isnull=True).count(),
        },
        "plot_groups": dict(
            projectless_plots.values("block__code").annotate(rows=Count("pk")).values_list("block__code", "rows")
        ),
        "bookings": bookings.count(),
        "selections": selections.count(),
        "hold_records": holds.count(),
        "unreleased_hold_records": holds.filter(released_at__isnull=True).count(),
        "linked_lead_projects": dict(linked_lead_projects),
    }


class Command(BaseCommand):
    help = "Assign projectless records for one organization to an explicitly selected project."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True)
        parser.add_argument("--project", required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            organization = Organization.objects.get(slug=options["org"], is_active=True)
        except Organization.DoesNotExist as error:
            raise CommandError("Organization not found.") from error
        try:
            project = Project.objects.get(organization=organization, code=options["project"])
        except Project.DoesNotExist as error:
            raise CommandError("Project code is not in the selected organization.") from error

        report = collect_assignment_report(organization)
        counts = report["counts"]
        self.stdout.write(
            f"organization={organization.slug} project={project.code} "
            f"dry_run={'true' if options['dry_run'] else 'false'}"
        )
        self.stdout.write("counts " + " ".join(f"{key}={value}" for key, value in counts.items()))
        for block_code, rows in sorted(report["plot_groups"].items()):
            self.stdout.write(f"plot_group block_code={block_code} rows={rows}")
        self.stdout.write(
            "relations "
            f"bookings={report['bookings']} selections={report['selections']} "
            f"hold_records={report['hold_records']} "
            f"unreleased_hold_records={report['unreleased_hold_records']}"
        )
        for project_code, count in sorted(report["linked_lead_projects"].items()):
            self.stdout.write(f"linked_lead_project={project_code} count={count}")
        if not report["linked_lead_projects"]:
            self.stdout.write("linked_lead_projects=none")

        if options["dry_run"]:
            return

        with transaction.atomic():
            for model in (Block, Plot, Lead, Sitevisit, Expense):
                rows = list(model.objects.filter(organization=organization, project__isnull=True))
                model.objects.filter(pk__in=[row.pk for row in rows]).update(project=project)
                if rows:
                    log_bulk_audit(module="settings", action="bulk_update", instances=rows,
                                   organization=organization, project=project,
                                   changed_values={"project_id": project.pk},
                                   route="command:assign_missing_projects")
        self.stdout.write("applied " + " ".join(f"{key}={value}" for key, value in counts.items()))
