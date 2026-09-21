from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership


class TelecallingTeamManagementTests(TestCase):
    """FR-P6-07: role-scoped queue analytics and queue redistribution."""

    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")

        self.manager_user = user_model.objects.create_user(username="manager-p607", password="test-pass")
        self.caller_user = user_model.objects.create_user(username="caller-p607", password="test-pass")
        self.target_user = user_model.objects.create_user(username="target-p607", password="test-pass")
        self.foreign_user = user_model.objects.create_user(username="foreign-p607", password="test-pass")

        self.manager = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager_user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.caller = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.caller_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.target = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.target_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.foreign_caller = OrganizationMembership.objects.create(
            organization=self.other_organization,
            user=self.foreign_user,
            role=OrganizationMembership.Role.TELECALLER,
        )

        self.client = APIClient()
        self.analytics_url = reverse("leads:telecalling-analytics", args=[self.organization.slug])
        self.redistribute_url = reverse("leads:telecalling-redistribute", args=[self.organization.slug])
        self.queue_url = reverse("leads:telecalling-queue", args=[self.organization.slug])

    def create_call(
        self,
        name,
        membership,
        *,
        organization=None,
        called_at=None,
        outcome="",
        next_follow_up=None,
    ):
        organization = organization or self.organization
        lead = Lead.objects.create(
            organization=organization,
            first_name=name,
            phone=f"9888{Lead.objects.count():06d}",
            assigned_membership=membership,
        )
        call = FollowUpCall.objects.create(
            organization=organization,
            lead=lead,
            telecaller_membership=membership,
            called_at=called_at,
            outcome=outcome,
            next_follow_up=next_follow_up,
        )
        return lead, call

    def test_manager_sees_organization_team_analytics_with_per_caller_breakdown(self):
        now = timezone.now()
        self.create_call("Pending", self.caller)
        self.create_call(
            "Connected",
            self.caller,
            called_at=now,
            outcome="interested",
            next_follow_up=now + timedelta(days=1),
        )
        self.create_call(
            "No answer",
            self.target,
            called_at=now,
            outcome="no_answer",
        )
        self.create_call(
            "Foreign",
            self.foreign_caller,
            organization=self.other_organization,
            called_at=now,
            outcome="interested",
        )

        self.client.force_authenticate(self.manager_user)
        response = self.client.get(self.analytics_url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["team"]["telecaller_count"], 2)
        self.assertEqual(response.data["totals"], {
            "queue_count": 3,
            "pending_count": 1,
            "completed_calls": 2,
            "connected_calls": 1,
            "follow_up_count": 1,
        })
        self.assertEqual(response.data["by_disposition"], {"interested": 1, "no_answer": 1})
        by_id = {row["telecaller"]["id"]: row for row in response.data["telecallers"]}
        self.assertEqual(by_id[self.caller.id]["queue_count"], 2)
        self.assertEqual(by_id[self.caller.id]["completed_calls"], 1)
        self.assertEqual(by_id[self.target.id]["queue_count"], 1)
        self.assertNotIn(self.foreign_caller.id, by_id)

    def test_manager_redistributes_pending_queue_and_both_queue_views_change(self):
        first_lead, first_call = self.create_call("First", self.caller)
        second_lead, second_call = self.create_call("Second", self.caller)

        self.client.force_authenticate(self.manager_user)
        response = self.client.post(self.redistribute_url, {
            "call_ids": [first_call.id, second_call.id],
            "telecaller_membership_id": self.target.id,
        }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["redistributed"], 2)
        first_call.refresh_from_db()
        second_call.refresh_from_db()
        first_lead.refresh_from_db()
        second_lead.refresh_from_db()
        self.assertEqual(first_call.telecaller_membership_id, self.target.id)
        self.assertEqual(second_call.telecaller_membership_id, self.target.id)
        self.assertEqual(first_lead.assigned_membership_id, self.target.id)
        self.assertEqual(second_lead.assigned_membership_id, self.target.id)

        self.client.force_authenticate(self.caller_user)
        self.assertEqual(self.client.get(self.queue_url).data["count"], 0)
        self.client.force_authenticate(self.target_user)
        self.assertEqual(self.client.get(self.queue_url).data["count"], 2)

    def test_telecaller_cannot_access_team_analytics_or_redistribute(self):
        _, call = self.create_call("Own", self.caller)
        self.client.force_authenticate(self.caller_user)

        analytics = self.client.get(self.analytics_url)
        redistribution = self.client.post(self.redistribute_url, {
            "call_ids": [call.id],
            "telecaller_membership_id": self.target.id,
        }, format="json")

        self.assertEqual(analytics.status_code, 403)
        self.assertEqual(redistribution.status_code, 403)
        call.refresh_from_db()
        self.assertEqual(call.telecaller_membership_id, self.caller.id)

    def test_redistribution_is_atomic_when_any_call_is_completed(self):
        now = timezone.now()
        _, pending = self.create_call("Pending", self.caller)
        _, completed = self.create_call("Completed", self.caller, called_at=now, outcome="busy")
        self.client.force_authenticate(self.manager_user)

        response = self.client.post(self.redistribute_url, {
            "call_ids": [pending.id, completed.id],
            "telecaller_membership_id": self.target.id,
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        pending.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(pending.telecaller_membership_id, self.caller.id)
        self.assertEqual(completed.telecaller_membership_id, self.caller.id)

    def test_redistribution_rejects_foreign_target_and_foreign_queue_item(self):
        _, own_call = self.create_call("Own", self.caller)
        _, foreign_call = self.create_call(
            "Foreign",
            self.foreign_caller,
            organization=self.other_organization,
        )
        self.client.force_authenticate(self.manager_user)

        foreign_target = self.client.post(self.redistribute_url, {
            "call_ids": [own_call.id],
            "telecaller_membership_id": self.foreign_caller.id,
        }, format="json")
        foreign_item = self.client.post(self.redistribute_url, {
            "call_ids": [own_call.id, foreign_call.id],
            "telecaller_membership_id": self.target.id,
        }, format="json")

        self.assertEqual(foreign_target.status_code, 400)
        self.assertEqual(foreign_item.status_code, 400)
        own_call.refresh_from_db()
        self.assertEqual(own_call.telecaller_membership_id, self.caller.id)
