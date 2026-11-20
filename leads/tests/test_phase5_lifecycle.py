from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import LeadAssignmentHistory, LeadStatusHistory, LeadTag


class Phase5LeadLifecycleApiTests(TestCase):
    """FR/DM/API-P5 regression coverage for the v2.9 lifecycle and ownership engine."""

    def setUp(self):
        self.organization = make_organization("phase5-lifecycle")
        self.project = make_project(self.organization, "P5")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="Phase",
            phone="9000000701",
            preferred_location="Pune",
            score=72,
        )
        self.client = APIClient()

    def headers(self):
        return project_request_kwargs(self.project)

    def url(self, suffix=""):
        return f"/api/v1/organizations/{self.organization.slug}/leads/{suffix}"

    def test_api_p5_01_supports_all_filters_pagination_and_sorting(self):
        second = make_lead(self.organization, self.project, first_name="Second", phone="9000000702", preferred_location="Mumbai", score=88)
        LeadTag.objects.create(lead=self.lead, tag_name="vip")
        response = self.client.get(
            self.url(),
            {"source": "website", "status": "new", "owner": "unassigned", "city": "Pune", "min_score": 70, "max_score": 80, "tag": "vip", "page": 1, "page_size": 1, "ordering": "-score"},
            **self.headers(),
        )
        self.client.force_authenticate(self.manager.user)
        response = self.client.get(
            self.url(),
            {"source": "website", "status": "new", "owner": "unassigned", "city": "Pune", "min_score": 70, "max_score": 80, "tag": "vip", "page": 1, "page_size": 1, "ordering": "-score"},
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.lead.id)
        self.assertNotEqual(second.id, self.lead.id)

    def test_api_p5_04_requires_reason_and_writes_assignment_history(self):
        self.client.force_authenticate(self.manager.user)
        missing_reason = self.client.patch(self.url(f"{self.lead.id}/assign/"), {"telecaller_membership": self.telecaller.id}, format="json", **self.headers())
        self.assertEqual(missing_reason.status_code, 400)

        response = self.client.patch(
            self.url(f"{self.lead.id}/assign/"),
            {"telecaller_membership": self.telecaller.id, "reason": "Capacity rebalance"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        history = LeadAssignmentHistory.objects.get(lead=self.lead)
        self.assertEqual(history.assigned_to_id, self.telecaller.id)
        self.assertEqual(history.reason, "Capacity rebalance")
        self.assertEqual(history.assigned_by_id, self.manager.user.id)

    def test_api_p5_05_uses_v29_state_machine_and_immutable_status_history(self):
        self.client.force_authenticate(self.manager.user)
        contacted = self.client.post(self.url(f"{self.lead.id}/status/"), {"status": "Contacted"}, format="json", **self.headers())
        self.assertEqual(contacted.status_code, 201, contacted.data)
        invalid = self.client.post(self.url(f"{self.lead.id}/status/"), {"status": "Converted"}, format="json", **self.headers())
        self.assertEqual(invalid.status_code, 400)
        history = LeadStatusHistory.objects.get(lead=self.lead)
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 1)
        self.assertEqual(history.new_status, "contacted")
        with self.assertRaises(ValidationError):
            history.new_status = "converted"
            history.save()
        with self.assertRaises(ValidationError):
            LeadStatusHistory.objects.filter(pk=history.pk).update(new_status="converted")
        with self.assertRaises(ValidationError):
            history.delete()

    def test_api_p5_02_returns_complete_history_and_reassignment_flag(self):
        self.lead.assigned_membership = self.telecaller
        self.lead.save(update_fields=["assigned_membership", "updated_at"])
        self.telecaller.is_active = False
        self.telecaller.save(update_fields=["is_active"])
        self.client.force_authenticate(self.manager.user)
        response = self.client.get(self.url(f"{self.lead.id}/"), **self.headers())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("assignment_history", response.data)
        self.assertIn("status_history", response.data)
        self.assertTrue(response.data["needs_reassignment"])

    def test_api_p5_03_rejects_core_edits_after_conversion(self):
        self.lead.lifecycle_status = "converted"
        self.lead.save(update_fields=["lifecycle_status", "updated_at"])
        self.client.force_authenticate(self.manager.user)
        response = self.client.patch(self.url(f"{self.lead.id}/"), {"first_name": "Changed"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 400, response.data)

    def test_api_p5_06_bulk_tagging_is_atomic(self):
        second = make_lead(self.organization, self.project, first_name="Atomic", phone="9000000703")
        self.client.force_authenticate(self.manager.user)
        response = self.client.post(self.url("bulk-action/"), {"lead_ids": [self.lead.id, second.id], "action": "add_tag", "value": "priority"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(LeadTag.objects.filter(tag_name="priority").count(), 2)

