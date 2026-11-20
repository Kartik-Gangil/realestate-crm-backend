from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import FollowUpCall, Lead


class TelecallerManualLeadTests(TestCase):
    """FR-P4-06 v2.6: telecaller lead creation is creator-owned and queue-ready."""

    def setUp(self):
        self.organization = make_organization("phase4-step8")
        self.project = make_project(self.organization, "MAIN")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.client = APIClient()

    def manual(self, user, payload):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/manual/",
            payload,
            format="json",
            **project_request_kwargs(self.project),
        )

    def test_telecaller_lead_is_assigned_and_queued_with_pending_follow_up(self):
        response = self.manual(self.telecaller.user, {
            "first_name": "Created",
            "phone": "9000000801",
            "source": "website",
            "assigned_membership": self.other_telecaller.id,
        })

        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data["id"])
        self.assertEqual(lead.assigned_membership_id, self.telecaller.id)
        self.assertTrue(FollowUpCall.objects.filter(
            lead=lead,
            telecaller_membership=self.telecaller,
            called_at__isnull=True,
        ).exists())

        queue = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/telecalling/queue/",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertIn(lead.id, {item["id"] for item in queue.data["results"]})

    def test_telecaller_owner_is_ignored(self):
        response = self.manual(self.telecaller.user, {
            "first_name": "Owner Ignored",
            "phone": "9000000802",
            "source": "website",
            "assigned_membership": self.other_telecaller.id,
        })

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Lead.objects.get(pk=response.data["id"]).assigned_membership_id, self.telecaller.id)

    def test_manager_with_edit_permission_can_choose_owner(self):
        response = self.manual(self.manager.user, {
            "first_name": "Manager Created",
            "phone": "9000000803",
            "source": "website",
            "assigned_membership": self.telecaller.id,
        })

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Lead.objects.get(pk=response.data["id"]).assigned_membership_id, self.telecaller.id)

    def test_telecaller_duplicate_outside_scope_contains_only_limited_details(self):
        existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Private Existing",
            phone="9000000804",
            source=Lead.Source.WEBSITE,
            assigned_membership=self.other_telecaller,
        )

        response = self.manual(self.telecaller.user, {
            "first_name": "Private Existing",
            "phone": "9000000804",
            "source": "website",
        })

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(set(response.data["matches"][0]), {"score", "rule", "lead_code"})
        self.assertEqual(response.data["matches"][0]["lead_code"], existing.lead_code)

    def test_telecaller_cannot_merge_into_duplicate_outside_scope(self):
        existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Private Merge Target",
            phone="9000000805",
            source=Lead.Source.WEBSITE,
            assigned_membership=self.other_telecaller,
        )

        response = self.manual(self.telecaller.user, {
            "first_name": "Private Merge Target",
            "phone": "9000000805",
            "source": "website",
            "resolution": "merge",
            "merge_into": existing.id,
        })

        self.assertEqual(response.status_code, 403, response.data)
