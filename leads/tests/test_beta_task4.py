from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone

from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import FollowUpCall
from leads.serializers import lead_to_dict


class BetaTask4LeadRouteTests(TestCase):
    """G-2 / FR-P5 / API-P5 regression tests for the Beta lead flow."""

    def setUp(self):
        self.organization = make_organization("demo-beta-task4")
        self.project = make_project(self.organization, "DEMO")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = make_lead(self.organization, self.project, first_name="Route", phone="9000000666", source="website")
        self.client = APIClient()

    def headers(self):
        return project_request_kwargs(self.project)

    def test_canonical_assign_status_and_bulk_routes_are_real_v1_routes(self):
        self.client.force_authenticate(self.manager.user)
        assign = self.client.patch(
            f"/api/v1/organizations/{self.organization.slug}/leads/{self.lead.id}/assign/",
            {"telecaller_membership": self.telecaller.id, "reason": "Beta assignment"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(assign.status_code, 200, assign.data)

        status_response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/{self.lead.id}/status/",
            {"status": "contacted", "reason": "First call"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(status_response.status_code, 201, status_response.data)

        bulk = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/bulk-action/",
            {"lead_ids": [self.lead.id], "action": "status", "value": "qualified"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(bulk.status_code, 200, bulk.data)

    def test_canonical_call_log_refuses_a_new_to_qualified_jump(self):
        self.lead.assigned_membership = self.telecaller
        self.lead.save(update_fields=["assigned_membership", "updated_at"])
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/calls/log/",
            {"lead_id": self.lead.id, "disposition": "Busy", "status": "qualified"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_canonical_call_log_refuses_a_new_to_interested_jump_with_transition_error(self):
        self.lead.assigned_membership = self.telecaller
        self.lead.save(update_fields=["assigned_membership", "updated_at"])
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/calls/log/",
            {"lead_id": self.lead.id, "disposition": "Busy", "status": "interested"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["status"], ["Cannot change lead status from 'new'."])
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "new")

    def test_assigned_membership_has_a_display_value_when_user_name_is_empty(self):
        self.lead.assigned_membership = self.telecaller
        self.lead.save(update_fields=["assigned_membership", "updated_at"])

        self.assertEqual(
            lead_to_dict(self.lead)["assigned_membership"],
            self.telecaller.user.email,
        )

    def test_calling_queue_exposes_lifecycle_status_separately_from_pending_disposition(self):
        self.lead.assigned_membership = self.telecaller
        self.lead.lifecycle_status = "interested"
        self.lead.save(update_fields=["assigned_membership", "lifecycle_status", "updated_at"])
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.lead,
            telecaller_membership=self.telecaller,
            status="new",
            next_follow_up=timezone.now(),
        )

        self.client.force_authenticate(self.telecaller.user)
        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/queue/",
            **self.headers(),
        )

        self.assertEqual(response.status_code, 200, response.data)
        queued = next(item for item in response.data["results"] if item["id"] == self.lead.id)
        self.assertEqual(queued["status"], "new")
        self.assertEqual(queued["lifecycle_status"], "interested")
