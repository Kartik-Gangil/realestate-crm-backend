from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from expenses.models import Expense, ExpenseCategory
from leads.models import Lead, Sitevisit
from organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    ProjectAssignment,
)

from .models import Block, Plot, PlotBooking, Project


class ProjectDataReportCommandTests(TestCase):
    """G-3 items 1 and 8: report project-isolation data without changing rows."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="report-user@example.test",
            email="private-report@example.test",
            password="password123",
        )
        self.organization = Organization.objects.create(name="Private Organization", slug="private-org")
        self.other_organization = Organization.objects.create(name="Other Organization", slug="other-org")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Project Manager",
            code="project-manager",
        )
        self.first_project = Project.objects.create(
            organization=self.organization,
            name="First Project",
            code="FIRST",
        )
        self.second_project = Project.objects.create(
            organization=self.organization,
            name="Second Project",
            code="SECOND",
        )
        Project.objects.create(
            organization=self.other_organization,
            name="Other Project",
            code="OTHER",
        )

        # One legacy membership link has no assignment; one assignment is not
        # represented in assigned_memberships. DM-P3-04 / G-1 item 7.
        self.first_project.assigned_memberships.add(self.membership)
        ProjectAssignment.objects.create(
            membership=self.membership,
            project=self.second_project,
            role=self.role,
        )

        self.default_block = Block.objects.create(
            organization=self.organization, project=self.first_project,
            name="Default Block",
            code="DEFAULT",
        )
        self.second_block = Block.objects.create(
            organization=self.organization,
            project=self.second_project,
            name="Second Block",
            code="SECOND",
        )
        self.first_plot = Plot.objects.create(
            organization=self.organization,
            project=self.first_project,
            block=self.default_block,
            plot_number="1",
            size=Decimal("100"),
        )
        Plot.objects.create(
            organization=self.organization, project=self.first_project,
            block=self.default_block,
            plot_number="unassigned",
            size=Decimal("100"),
        )
        self.second_plot = Plot.objects.create(
            organization=self.organization,
            project=self.second_project,
            block=self.second_block,
            plot_number="2",
            size=Decimal("100"),
        )
        Lead.objects.create(
            organization=self.organization,
            project=self.first_project,
            first_name="Unassigned",
            phone="9000000001",
        )
        first_lead = Lead.objects.create(
            organization=self.organization,
            project=self.first_project,
            first_name="First",
            phone="9000000002",
        )
        Sitevisit.objects.create(
            organization=self.organization,
            project=self.first_project,
            lead=first_lead,
            visit_date="2026-11-02",
        )
        Sitevisit.objects.create(
            organization=self.organization,
            project=self.second_project,
            lead=first_lead,
            visit_date="2026-11-03",
        )
        PlotBooking.objects.create(
            organization=self.organization,
            lead=first_lead,
            plot=self.second_plot,
        )
        ExpenseCategory.objects.create(
            organization=self.organization,
            project=self.first_project,
            name="Unassigned Category",
        )
        Expense.objects.create(
            organization=self.organization,
            project=self.first_project,
            expense_id="EXP-REPORT-1",
            submitted_by=self.user,
            category=ExpenseCategory.objects.get(organization=self.organization),
            amount=Decimal("100"),
            description="Unassigned expense",
        )

        # Every project-scope row is assigned before the required-project
        # migration. The report must not print organization names, names,
        # phones, or emails. G-3 item 1.
        self.assertEqual(Block.objects.filter(organization=self.organization, project__isnull=True).count(), 0)
        self.assertEqual(Plot.objects.filter(organization=self.organization, project__isnull=True).count(), 0)

    def test_project_data_report_is_counts_only_and_read_only_fr_p0_01_fr_p0_02_gnfr_06(self):
        before = {
            "projects": Project.objects.count(),
            "leads": Lead.objects.count(),
            "sitevisits": Sitevisit.objects.count(),
            "blocks": Block.objects.count(),
            "plots": Plot.objects.count(),
            "expenses": Expense.objects.count(),
            "assignments": ProjectAssignment.objects.count(),
        }
        output = StringIO()

        call_command("project_data_report", stdout=output)

        text = output.getvalue()
        self.assertIn("organization=private-org projects=2", text)
        self.assertIn("no_project Lead=0 Sitevisit=0 Block=0 Plot=0 Expense=0", text)
        self.assertIn("assignment_gaps assigned_memberships_without_assignment=1 assignments_without_assigned_membership=1", text)
        self.assertIn("cross_project bookings=1 sitevisits=1", text)
        self.assertIn("organization=other-org projects=1", text)
        self.assertNotIn("Private Organization", text)
        self.assertNotIn("private-report@example.test", text)
        self.assertNotIn("9000000001", text)

        after = {
            "projects": Project.objects.count(),
            "leads": Lead.objects.count(),
            "sitevisits": Sitevisit.objects.count(),
            "blocks": Block.objects.count(),
            "plots": Plot.objects.count(),
            "expenses": Expense.objects.count(),
            "assignments": ProjectAssignment.objects.count(),
        }
        self.assertEqual(before, after)
