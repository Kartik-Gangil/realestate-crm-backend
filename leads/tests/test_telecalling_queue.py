from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership


class TelecallingQueueApiTests(TestCase):
    """FR-P6-01 / NFR-P6-01: dynamic, scoped call-queue ordering."""

    def setUp(self):
        user_model = get_user_model()
        self.manager_user = user_model.objects.create_user(username="manager", password="test-pass")
        self.telecaller_user = user_model.objects.create_user(username="telecaller", password="test-pass")
        self.other_telecaller_user = user_model.objects.create_user(username="other-telecaller", password="test-pass")
        self.foreign_user = user_model.objects.create_user(username="foreign", password="test-pass")

        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.foreign_organization = Organization.objects.create(name="Foreign", slug="foreign")
        self.manager = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager_user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.telecaller = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.telecaller_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.other_telecaller = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_telecaller_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.foreign_telecaller = OrganizationMembership.objects.create(
            organization=self.foreign_organization,
            user=self.foreign_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.client = APIClient()
        self.url = reverse("leads:telecalling-queue", args=[self.organization.slug])

    def create_call(
        self,
        name,
        *,
        membership=None,
        organization=None,
        next_follow_up=None,
        called_at=None,
        outcome="",
    ):
        organization = organization or self.organization
        membership = membership or self.telecaller
        lead = Lead.objects.create(
            organization=organization,
            first_name=name,
            phone=f"900000{Lead.objects.count():04d}",
            assigned_membership=membership,
        )
        call = FollowUpCall.objects.create(
            organization=organization,
            lead=lead,
            telecaller_membership=membership,
            next_follow_up=next_follow_up,
            called_at=called_at,
            outcome=outcome,
        )
        return lead, call

    def test_pending_attempts_are_first_then_earliest_follow_up_with_stable_ties(self):
        now = timezone.now()
        completed_lead, _ = self.create_call(
            "Completed",
            next_follow_up=now + timedelta(hours=1),
            called_at=now,
            outcome="interested",
        )
        later_lead, _ = self.create_call("Later", next_follow_up=now + timedelta(hours=4))
        first_tie_lead, _ = self.create_call("First tie", next_follow_up=now + timedelta(hours=2))
        second_tie_lead, _ = self.create_call("Second tie", next_follow_up=now + timedelta(hours=2))

        self.client.force_authenticate(self.manager_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [item["lead"]["id"] for item in response.data["results"]],
            [first_tie_lead.id, second_tie_lead.id, later_lead.id, completed_lead.id],
        )
        self.assertEqual([item["is_pending_attempt"] for item in response.data["results"]], [True, True, True, False])

    def test_queue_contains_only_the_latest_attempt_for_each_lead(self):
        now = timezone.now()
        lead, old_call = self.create_call(
            "Retried",
            called_at=now - timedelta(hours=1),
            outcome="no_answer",
        )
        latest = FollowUpCall.objects.create(
            organization=self.organization,
            lead=lead,
            telecaller_membership=self.telecaller,
            next_follow_up=now + timedelta(hours=1),
        )

        self.client.force_authenticate(self.manager_user)
        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], latest.id)
        self.assertNotEqual(response.data["results"][0]["id"], old_call.id)

    def test_telecaller_sees_own_queue_and_manager_sees_team_queue(self):
        own_lead, _ = self.create_call("Own")
        team_lead, _ = self.create_call("Team", membership=self.other_telecaller)
        self.create_call(
            "Foreign",
            membership=self.foreign_telecaller,
            organization=self.foreign_organization,
        )

        self.client.force_authenticate(self.telecaller_user)
        response = self.client.get(self.url)
        self.assertEqual([item["lead"]["id"] for item in response.data["results"]], [own_lead.id])

        self.client.force_authenticate(self.manager_user)
        response = self.client.get(self.url)
        self.assertEqual(
            {item["lead"]["id"] for item in response.data["results"]},
            {own_lead.id, team_lead.id},
        )

    def test_tabs_and_pagination_are_supported(self):
        now = timezone.now()
        pending_lead, _ = self.create_call("Pending")
        connected_lead, _ = self.create_call(
            "Connected",
            called_at=now,
            outcome="interested",
        )
        follow_up_lead, _ = self.create_call(
            "Follow up",
            called_at=now,
            outcome="callback_later",
            next_follow_up=now + timedelta(days=1),
        )

        self.client.force_authenticate(self.manager_user)
        pending = self.client.get(self.url, {"tab": "pending"})
        connected = self.client.get(self.url, {"tab": "connected"})
        follow_ups = self.client.get(self.url, {"tab": "follow_ups"})
        page = self.client.get(self.url, {"page": 2, "page_size": 1})

        self.assertEqual([item["lead"]["id"] for item in pending.data["results"]], [pending_lead.id])
        self.assertEqual(
            [item["lead"]["id"] for item in connected.data["results"]],
            [follow_up_lead.id, connected_lead.id],
        )
        self.assertEqual([item["lead"]["id"] for item in follow_ups.data["results"]], [follow_up_lead.id])
        self.assertEqual(page.data["count"], 3)
        self.assertEqual(page.data["page"], 2)
        self.assertEqual(page.data["page_size"], 1)
        self.assertIsNotNone(page.data["next"])
        self.assertIsNotNone(page.data["previous"])

    def test_invalid_tab_and_pagination_return_validation_errors(self):
        self.client.force_authenticate(self.manager_user)
        self.assertEqual(self.client.get(self.url, {"tab": "unknown"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"page": "bad"}).status_code, 400)
