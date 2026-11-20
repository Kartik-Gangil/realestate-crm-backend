from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Notification
from core.notifications import notify
from core.tests.factories import make_member, make_organization, make_project


class NotificationTests(TestCase):
    """DM-P0-03, UI-P0-05 and G-0 notification fallback coverage."""

    def setUp(self):
        self.client = APIClient()
        self.organization = make_organization("notification-org")
        self.project = make_project(self.organization, "NOTIFY")
        self.other_project = make_project(self.organization, "OTHER")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.other_membership = make_member(self.organization, role="manager", projects=[self.other_project])

    def test_notify_requires_same_organization_and_keeps_related_ids_out_of_copy(self):
        notification = notify(
            self.membership,
            "site_visit_reminder",
            "Site visit reminder",
            "Your scheduled visit is ready.",
            related=("leads.Lead", 99),
            project=self.project,
        )

        self.assertEqual(notification.recipient_membership_id, self.membership.id)
        self.assertEqual(notification.related_object_id, 99)
        self.assertNotIn("99", notification.title)
        self.assertNotIn("99", notification.body)
        foreign_org = make_organization("foreign-notify-org")
        foreign_project = make_project(foreign_org, "FOREIGN")
        with self.assertRaises(ValidationError):
            notify(self.membership, "bad", "Bad", "Bad", project=foreign_project)

    def test_v1_notifications_are_own_newest_first_filtered_and_paginated_g0_dm_p0_03(self):
        older = notify(self.membership, "older", "Older", "Old body")
        newer = notify(self.membership, "newer", "Newer", "New body", project=self.project)
        notify(self.other_membership, "other", "Other", "Other body", project=self.other_project)

        self.client.force_authenticate(self.membership.user)
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/notifications/?page_size=1")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["count"], 2)
        self.assertEqual(body["data"]["results"][0]["id"], newer.id)
        self.assertNotIn(older.id, [item["id"] for item in body["data"]["results"]])

        read = self.client.post(f"/api/v1/organizations/{self.organization.slug}/notifications/{newer.id}/read/")
        self.assertEqual(read.status_code, 200)
        self.assertEqual(Notification.objects.get(pk=newer.id).status, Notification.Status.READ)
        self.client.post(f"/api/v1/organizations/{self.organization.slug}/notifications/read-all/")
        self.assertEqual(Notification.objects.filter(recipient_membership=self.membership, status=Notification.Status.PENDING).count(), 0)

