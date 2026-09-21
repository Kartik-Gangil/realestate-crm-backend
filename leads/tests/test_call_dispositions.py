from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership
from system_settings.models import MasterData


EXPECTED_DISPOSITIONS = [
    ("interested", "Interested"),
    ("callback_later", "Callback Later"),
    ("busy", "Busy"),
    ("no_answer", "No Answer"),
    ("switched_off", "Switched Off"),
    ("wrong_number", "Wrong Number"),
    ("dnd", "DND"),
    ("already_purchased", "Already Purchased"),
]


class CallDispositionApiTests(TestCase):
    """FR-P6-03: fixed call dispositions bound to organization master data."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="caller", password="test-pass")
        self.admin_user = user_model.objects.create_user(username="admin", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin_user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            first_name="Ravi",
            phone="9999999999",
            assigned_membership=self.membership,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.list_url = reverse("leads:telecalling-dispositions", args=[self.organization.slug])
        self.log_url = reverse("leads:telecalling-call-log", args=[self.organization.slug])

    def test_list_seeds_and_returns_exact_active_master_data_set(self):
        MasterData.objects.create(
            organization=self.other_organization,
            master_type="call_disposition",
            code="foreign_only",
            name="Foreign Only",
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [(item["code"], item["name"]) for item in response.data["results"]],
            EXPECTED_DISPOSITIONS,
        )
        self.assertEqual(
            MasterData.objects.filter(
                organization=self.organization,
                master_type="call_disposition",
            ).count(),
            8,
        )
        self.assertNotIn("foreign_only", [item["code"] for item in response.data["results"]])

    def test_manual_log_accepts_active_master_disposition_and_rejects_inactive_or_unknown(self):
        self.client.get(self.list_url)
        response = self.client.post(
            self.log_url,
            {
                "lead_id": self.lead.id,
                "disposition": "interested",
                "notes": "Ready for visit.",
                "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(FollowUpCall.objects.get(pk=response.data["id"]).outcome, "interested")

        MasterData.objects.filter(
            organization=self.organization,
            master_type="call_disposition",
            code="busy",
        ).update(is_active=False)
        response = self.client.post(
            self.log_url,
            {"lead_id": self.lead.id, "disposition": "busy", "notes": "Busy."},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        unknown = self.client.post(
            self.log_url,
            {"lead_id": self.lead.id, "disposition": "connected", "notes": "Unknown."},
            format="json",
        )
        self.assertEqual(unknown.status_code, 400)

    def test_fixed_disposition_codes_cannot_be_added_renamed_or_deleted(self):
        self.client.get(self.list_url)
        item = MasterData.objects.get(
            organization=self.organization,
            master_type="call_disposition",
            code="interested",
        )
        self.client.force_authenticate(self.admin_user)
        collection = f"/api/organizations/{self.organization.slug}/settings/masters/call_disposition/"
        detail = f"{collection}{item.id}/"

        self.assertEqual(
            self.client.post(collection, {"code": "custom", "name": "Custom"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(detail, {"code": "renamed"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client.delete(detail, {"confirmation": True}, format="json").status_code,
            409,
        )
        deactivate = self.client.patch(detail, {"is_active": False}, format="json")
        self.assertEqual(deactivate.status_code, 200, deactivate.data)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
