from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership, Project
from system_settings.models import MasterData


class Phase2SiteVisitOutcomeMasterDataTests(APITestCase):
    """FR-P2-01 / FR-P7-04 / GNFR-09: outcomes use active project master data."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="outcome-manager",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Outcome Org", slug="outcome-org")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Outcome Project",
            code="OUTCOME",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Other Outcome Project",
            code="OTHER-OUTCOME",
        )
        self.lead = Lead.all_objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Asha",
            phone="9000000020",
        )
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)

    def create_visit(self):
        return Sitevisit.all_objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.membership,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            status=Sitevisit.Status.IN_PROGRESS,
        )

    def submit(self, visit, outcome, interest_level=4):
        return self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/sitevisits/{visit.id}/outcome/",
            {"outcome": outcome, "interest_level": interest_level},
            format="json",
        )

    def test_required_defaults_are_seeded_as_protected_items_and_accepted(self):
        response = self.submit(self.create_visit(), "interested")

        self.assertEqual(response.status_code, 200, response.data)
        outcomes = MasterData.all_objects.filter(
            organization=self.organization,
            project=self.project,
            master_type="site_visit_outcome",
        )
        self.assertEqual(
            set(outcomes.values_list("code", flat=True)),
            {
                "interested",
                "need_more_time",
                "price_issue",
                "location_issue",
                "loan_issue",
                "already_purchased",
                "wrong_requirement",
            },
        )
        self.assertFalse(outcomes.filter(is_system=False).exists())

    def test_active_project_custom_outcome_is_accepted_without_model_choices(self):
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.project,
            master_type="site_visit_outcome",
            code="documentation_pending",
            name="Documentation Pending",
        )

        response = self.submit(self.create_visit(), "documentation_pending")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["outcome"], "documentation_pending")
        self.assertFalse(Sitevisit._meta.get_field("outcome").choices)

    def test_inactive_outcome_is_rejected_immediately(self):
        self.submit(self.create_visit(), "interested")
        outcome = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="site_visit_outcome",
            code="price_issue",
        )
        outcome.is_active = False
        outcome.save(update_fields=["is_active"])

        response = self.submit(self.create_visit(), "price_issue")

        self.assertEqual(response.status_code, 400)
        self.assertIn("outcome", response.data)

    def test_other_project_outcome_is_rejected(self):
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.other_project,
            master_type="site_visit_outcome",
            code="other_project_only",
            name="Other Project Only",
        )

        response = self.submit(self.create_visit(), "other_project_only")

        self.assertEqual(response.status_code, 400)
        self.assertIn("outcome", response.data)

    def test_unknown_outcome_does_not_complete_visit(self):
        visit = self.create_visit()

        response = self.submit(visit, "unknown")

        self.assertEqual(response.status_code, 400)
        visit.refresh_from_db()
        self.assertEqual(visit.status, Sitevisit.Status.IN_PROGRESS)
        self.assertIsNone(visit.outcome)
