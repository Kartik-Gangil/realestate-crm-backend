from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.duplicate import score_duplicates
from leads.models import Lead
from system_settings.models import SystemParameter


class Phase4Step3DuplicateScoringTests(TestCase):
    """FR-P4-04 / NFR-P4-02 / NFR-P4-03 tests."""

    def setUp(self):
        cache.clear()
        self.organization = make_organization("phase4-step3")
        self.project = make_project(self.organization, "MAIN")
        self.other_project = make_project(self.organization, "OTHER")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)

    def make_lead(self, *, project=None, name="Alice Example", phone="9876543210", email="alice@example.com"):
        first_name, last_name = name.split(" ", 1)
        return Lead.objects.create(
            organization=self.organization,
            project=project or self.project,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            source="website",
        )

    def test_phone_exact_rule_uses_configured_score(self):
        lead = self.make_lead()
        matches = score_duplicates(self.organization, self.project, {"full_name": lead.full_name, "phone": "9876543210"})
        self.assertEqual(matches[0]["score"], 95)
        self.assertEqual(matches[0]["rule"], "phone_exact")

    def test_phone_different_name_rule_uses_configured_score(self):
        lead = self.make_lead(name="Alice Example")
        matches = score_duplicates(self.organization, self.project, {"full_name": "Bob Example", "phone": "9876543210"})
        self.assertEqual(matches[0]["score"], 90)
        self.assertEqual(matches[0]["rule"], "phone_different_name")

    def test_email_partial_phone_rule_uses_configured_score(self):
        lead = self.make_lead(phone="9876543210", email="alice@example.com")
        matches = score_duplicates(self.organization, self.project, {"full_name": "Someone Else", "phone": "1236543210", "email": "alice@example.com"})
        self.assertEqual(matches[0]["score"], 80)
        self.assertEqual(matches[0]["rule"], "email_partial_phone")

    def test_highest_score_wins_when_multiple_rules_match(self):
        self.make_lead(name="Alice Example", phone="9876543210", email="alice@example.com")
        matches = score_duplicates(self.organization, self.project, {"full_name": "Bob Example", "phone": "9876543210", "email": "alice@example.com"})
        self.assertEqual(matches[0]["score"], 90)
        self.assertEqual(matches[0]["rule"], "phone_different_name")

    def test_changed_system_parameter_changes_score(self):
        lead = self.make_lead()
        SystemParameter.objects.filter(project=self.project, parameter_key="duplicate_score_phone_exact").update(value=73)
        cache.clear()
        matches = score_duplicates(self.organization, self.project, {"full_name": lead.full_name, "phone": "9876543210"})
        self.assertEqual(matches[0]["score"], 73)

    def test_other_project_leads_are_not_matched(self):
        self.make_lead(project=self.other_project)
        matches = score_duplicates(self.organization, self.project, {"full_name": "Alice Example", "phone": "9876543210"})
        self.assertEqual(matches, [])

    def test_lead_save_stores_normalized_phone(self):
        lead = self.make_lead(phone="919876543210")
        self.assertEqual(lead.phone, "+919876543210")

    def test_duplicate_endpoint_returns_score_rule_and_lead_code(self):
        lead = self.make_lead()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/check-duplicate/",
            {"full_name": lead.full_name, "phone": "9876543210"},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["matches"][0]["score"], 95)
        self.assertEqual(response.data["matches"][0]["rule"], "phone_exact")
        self.assertEqual(response.data["matches"][0]["lead_code"], lead.lead_code)
