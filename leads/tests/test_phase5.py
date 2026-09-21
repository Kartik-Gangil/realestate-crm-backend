from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership, Project
from system_settings.master_data import ensure_lead_sources, ensure_lead_statuses

from leads.models import Lead, LeadAssignmentHistory, LeadStatusHistory, LeadTag


class Phase5LeadLifecycleTests(TestCase):
    """PHASE 5: FR-P5-01..FR-P5-08 and API-P5-01..API-P5-06."""

    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="p5-admin", email="p5-admin@test", password="Valid-password-1!")
        self.manager = user_model.objects.create_user(username="p5-manager", email="p5-manager@test", password="Valid-password-1!")
        self.telecaller = user_model.objects.create_user(username="p5-telecaller", email="p5-telecaller@test", password="Valid-password-1!")
        self.other = user_model.objects.create_user(username="p5-other", email="p5-other@test", password="Valid-password-1!")
        self.organization = Organization.objects.create(name="Phase 5 Realty", slug="phase5-realty")
        self.project = Project.objects.create(organization=self.organization, name="P5 Project", code="P5-PROJECT")
        self.admin_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role="admin")
        self.manager_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role="manager")
        self.telecaller_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.telecaller, role="telecaller")
        self.other_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.other, role="telecaller")
        ensure_lead_sources(self.organization)
        ensure_lead_statuses(self.organization)
        self.lead = Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Asha", last_name="Sharma",
            phone="9999999999", source="website", city="Pune", assigned_membership=self.telecaller_membership,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)
        self.client.force_authenticate(self.admin)

    def url(self, suffix):
        return f"/api/v1/organizations/{self.organization.slug}/{suffix.lstrip('/')}"

    def test_fr_p5_02_status_state_machine_and_immutable_history(self):
        valid = self.client.post(self.url(f"leads/{self.lead.id}/status/"), {"status": "contacted"}, format="json")
        invalid = self.client.post(self.url(f"leads/{self.lead.id}/status/"), {"status": "converted"}, format="json")
        self.assertEqual(valid.status_code, 200, valid.data)
        self.assertEqual(invalid.status_code, 400)
        history = LeadStatusHistory.objects.get(lead=self.lead)
        with self.assertRaises(ValidationError):
            history.reason = "tampered"
            history.save()

    def test_fr_p5_03_assignment_requires_reason_and_retains_history(self):
        missing = self.client.post(self.url(f"leads/{self.lead.id}/assign/"), {"telecaller_membership": self.other_membership.id}, format="json")
        assigned = self.client.post(
            self.url(f"leads/{self.lead.id}/assign/"),
            {"telecaller_membership": self.other_membership.id, "reason": "Workload balancing"}, format="json"
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(LeadAssignmentHistory.objects.get(lead=self.lead).reason, "Workload balancing")

    def test_fr_p5_01_filters_sorting_tags_and_pagination(self):
        LeadTag.objects.create(lead=self.lead, tag_name="priority")
        Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Ravi", phone="8888888888",
            source="website", city="Mumbai", status="contacted", score=80,
        )
        response = self.client.get(self.url("leads/"), {"city": "Pune", "tag": "priority", "page": 1, "page_size": 1, "ordering": "-score"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.lead.id)

    def test_fr_p5_04_bulk_action_is_transactional_and_adds_tag(self):
        other_lead = Lead.objects.create(organization=self.organization, project=self.project, first_name="Other", phone="7777777777", source="website")
        response = self.client.post(
            self.url("leads/bulk-action/"),
            {"lead_ids": [self.lead.id, other_lead.id], "action": "add_tag", "tag": "campaign-a"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(LeadTag.objects.filter(tag_name="campaign-a").count(), 2)

    def test_fr_p5_05_converted_lead_core_fields_are_immutable(self):
        self.lead.status = "converted"
        self.lead.save(update_fields=["status"])
        response = self.client.patch(self.url(f"leads/{self.lead.id}/"), {"phone": "1111111111"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.phone, "9999999999")

    def test_fr_p5_07_non_admin_can_edit_only_owned_lead(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(self.url(f"leads/{self.lead.id}/"), {"city": "Delhi"}, format="json")
        self.assertEqual(response.status_code, 404)

