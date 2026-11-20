from datetime import timedelta

from django.utils import timezone
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Notification
from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import FollowUpCall


class Phase6FinalSprintApiTests(TestCase):
    """FR/DM/API/NFR-P6 final-sprint gaps."""

    def setUp(self):
        self.organization = make_organization("phase6-final")
        self.project = make_project(self.organization, "P6")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.early = make_lead(self.organization, self.project, first_name="Early", phone="9000000801", assigned_membership=self.telecaller)
        self.late = make_lead(self.organization, self.project, first_name="Late", phone="9000000802", assigned_membership=self.telecaller)
        now = timezone.now()
        FollowUpCall.objects.create(organization=self.organization, lead=self.early, telecaller_membership=self.telecaller, next_follow_up=now + timedelta(hours=1), status="new")
        FollowUpCall.objects.create(organization=self.organization, lead=self.late, telecaller_membership=self.telecaller, next_follow_up=now + timedelta(days=1), status="new")
        self.client = APIClient()

    def headers(self):
        return project_request_kwargs(self.project)

    def test_nfr_p6_01_orders_pending_attempts_then_follow_up_time(self):
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/telecalling/queue/", **self.headers())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["results"][:2]], [self.early.id, self.late.id])

    def test_fr_p6_06_creates_pending_notification_for_required_follow_up(self):
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/calls/log/",
            {"lead_id": self.early.id, "disposition": "Callback Later", "notes": "Call tomorrow", "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.data)
        reminder = Notification.objects.get(related_object_id=self.early.id, type="telecalling.follow_up")
        self.assertEqual(reminder.status, Notification.Status.PENDING)
        self.assertEqual(reminder.recipient_membership_id, self.telecaller.id)

    def test_api_p6_04_creates_a_follow_up_through_the_standalone_contract(self):
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/follow-ups/",
            {"lead_id": self.early.id, "follow_up_date": (timezone.now() + timedelta(days=2)).isoformat(), "reason": "Budget discussion"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(FollowUpCall.objects.filter(lead=self.early, next_follow_up__isnull=False).exists())

