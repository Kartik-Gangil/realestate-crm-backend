from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead, LeadHistory
from organizations.models import Permission
from system_settings.models import AuditLog


class Phase4Step4ManualLeadTests(TestCase):
    """FR-P4-02 / FR-P4-05 / FR-P4-06 / API-P4-03 / API-P4-06 tests."""

    def setUp(self):
        self.organization = make_organization("phase4-step4")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        self.url = f"/api/v1/organizations/{self.organization.slug}/leads/manual/"
        self.kwargs = project_request_kwargs(self.project)

    def payload(self, **overrides):
        value = {
            "first_name": "New",
            "last_name": "Lead",
            "phone": "9876543210",
            "email": "new@example.com",
            "source": "website",
            "address": "New address",
        }
        value.update(overrides)
        return value

    def test_phone_is_required(self):
        response = self.client.post(self.url, self.payload(phone=""), format="json", **self.kwargs)
        self.assertEqual(response.status_code, 400)

    def test_duplicate_returns_409_and_saves_nothing(self):
        existing = Lead.objects.create(organization=self.organization, project=self.project, first_name="Existing", phone="9876543210", source="website")
        before = Lead.objects.count()
        response = self.client.post(self.url, self.payload(), format="json", **self.kwargs)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Lead.objects.count(), before)
        self.assertEqual(response.data["matches"][0]["lead_code"], existing.lead_code)

    def test_create_anyway_saves_the_lead(self):
        Lead.objects.create(organization=self.organization, project=self.project, first_name="Existing", phone="9876543210", source="website")
        response = self.client.post(self.url, {**self.payload(), "resolution": "create_anyway"}, format="json", **self.kwargs)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Lead.objects.filter(project=self.project).count(), 2)

    def test_merge_fills_only_empty_fields_and_writes_one_audit_row(self):
        existing = Lead.objects.create(organization=self.organization, project=self.project, first_name="Existing", last_name="Value", phone="9876543210", source="website", email="")
        before_audits = AuditLog.objects.filter(action="merge", module="leads").count()
        response = self.client.post(
            self.url,
            {**self.payload(email="filled@example.com"), "resolution": "merge", "merge_into": existing.id},
            format="json",
            **self.kwargs,
        )
        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Existing")
        self.assertEqual(existing.last_name, "Value")
        self.assertEqual(existing.email, "filled@example.com")
        self.assertEqual(Lead.objects.filter(project=self.project).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="merge", module="leads").count() - before_audits, 1)
        self.assertEqual(LeadHistory.objects.filter(lead=existing, action="merge").count(), 1)

    def test_merge_endpoint_merges_an_already_checked_lead_api_p4_06(self):
        existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="9876543210",
            source="website",
            email="",
        )
        source = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="New",
            phone="9876543211",
            source="website",
            email="filled@example.com",
        )
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/merge/",
            {"source_lead_id": source.pk, "target_lead_id": existing.pk},
            format="json",
            **self.kwargs,
        )
        self.assertEqual(response.status_code, 200, response.data)
        existing.refresh_from_db()
        self.assertEqual(existing.email, "filled@example.com")
        self.assertFalse(Lead.objects.filter(pk=source.pk).exists())
        self.assertEqual(LeadHistory.objects.filter(lead=existing, action="merge").count(), 1)

    def test_view_only_member_cannot_create(self):
        view_permission = Permission.objects.get(module="leads", action="view")
        self.membership.organization_role.permissions.set([view_permission])
        response = self.client.post(self.url, self.payload(phone="9876543211"), format="json", **self.kwargs)
        self.assertEqual(response.status_code, 403)
