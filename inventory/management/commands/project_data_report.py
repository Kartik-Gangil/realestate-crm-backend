from django.core.management.base import BaseCommand
from django.db.models import F

from expenses.models import Expense
from leads.models import Lead, Sitevisit
from organizations.models import Organization, ProjectAssignment

from inventory.models import Block, Plot, PlotBooking, Project


class Command(BaseCommand):
    help = "Report project-isolation counts without changing application data."

    def handle(self, *args, **options):
        legacy_link_model = Project.assigned_memberships.through

        for organization in Organization.objects.order_by("slug"):
            projects = Project.objects.filter(organization=organization)
            self.stdout.write(
                f"organization={organization.slug} projects={projects.count()}"
            )

            self.stdout.write(
                "no_project "
                f"Lead={Lead.objects.filter(organization=organization, project__isnull=True).count()} "
                f"Sitevisit={Sitevisit.objects.filter(organization=organization, project__isnull=True).count()} "
                f"Block={Block.objects.filter(organization=organization, project__isnull=True).count()} "
                f"Plot={Plot.objects.filter(organization=organization, project__isnull=True).count()} "
                f"Expense={Expense.objects.filter(organization=organization, project__isnull=True).count()}"
            )

            legacy_pairs = set(
                legacy_link_model.objects.filter(project__organization=organization).values_list(
                    "project_id", "organizationmembership_id"
                )
            )
            assignment_pairs = set(
                ProjectAssignment.objects.filter(project__organization=organization).values_list(
                    "project_id", "membership_id"
                )
            )
            self.stdout.write(
                "assignment_gaps "
                f"assigned_memberships_without_assignment={len(legacy_pairs - assignment_pairs)} "
                f"assignments_without_assigned_membership={len(assignment_pairs - legacy_pairs)}"
            )

            cross_project_bookings = PlotBooking.objects.filter(
                organization=organization,
                plot__project__isnull=False,
                lead__project__isnull=False,
            ).exclude(plot__project_id=F("lead__project_id")).count()
            cross_project_sitevisits = Sitevisit.objects.filter(
                organization=organization,
                project__isnull=False,
                lead__project__isnull=False,
            ).exclude(project_id=F("lead__project_id")).count()
            self.stdout.write(
                "cross_project "
                f"bookings={cross_project_bookings} sitevisits={cross_project_sitevisits}"
            )
