from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead
from organizations.models import OrganizationMembership
from system_settings.models import MasterData, MasterDataCategory


class TelecallerMasterDataAndManualLeadTests(TestCase):
    """FR-P4-02/API-P2-01/FR-P4-06 v2.6: lead forms use project master data."""

    def setUp(self):
        self.organization = make_organization("phase4-step9")
        self.project = make_project(self.organization, "MAIN")
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.admin = make_member(self.organization, role=OrganizationMembership.Role.ADMIN, projects=[self.project])
        self.client = APIClient()
        self.source = MasterData.objects.get(project=self.project, category__code="lead_source", code="website")
        self.status = MasterData.objects.get(project=self.project, category__code="lead_stage", code="new")

    def authenticate(self, membership):
        self.client.force_authenticate(membership.user)

    def master_data(self, category, membership=None, query=""):
        self.authenticate(membership or self.telecaller)
        return self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category}/?{query}" if query else
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category}/",
            **project_request_kwargs(self.project),
        )

    def manual(self, payload):
        self.authenticate(self.telecaller)
        return self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/manual/",
            payload,
            format="json",
            **project_request_kwargs(self.project),
        )

    def test_telecaller_reads_active_lead_master_data_without_settings_view(self):
        for category in ("lead_source", "lead_stage"):
            response = self.master_data(category)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.json()["data"])
            self.assertTrue(all(row["is_active"] for row in response.json()["data"]))

    def test_telecaller_cannot_post_or_put_master_data(self):
        self.authenticate(self.telecaller)
        post_response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/master-data/",
            {"category": "lead_source", "key": "referral", "value": "Referral"},
            format="json",
            **project_request_kwargs(self.project),
        )
        put_response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/master-data/lead_source/{self.source.pk}/",
            {"value": "Changed"},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(post_response.status_code, 403, post_response.data)
        self.assertEqual(put_response.status_code, 403, put_response.data)

    def test_user_without_project_access_gets_forbidden(self):
        other_project = make_project(self.organization, "OTHER")
        member = make_member(self.organization, role="telecaller", projects=[other_project])
        response = self.master_data("lead_source", member)
        self.assertEqual(response.status_code, 403, response.data)

    def test_inactive_items_are_hidden_without_settings_view_and_visible_with_it(self):
        inactive = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=self.source.category,
            code="inactive_source",
            name="Inactive source",
            is_active=False,
        )

        restricted = self.master_data("lead_source", self.telecaller, "include_inactive=1")
        privileged = self.master_data("lead_source", self.admin, "include_inactive=1")

        self.assertNotIn(inactive.code, [row["key"] for row in restricted.json()["data"]])
        self.assertIn(inactive.code, [row["key"] for row in privileged.json()["data"]])

    def test_manual_create_without_status_uses_new_stage(self):
        response = self.manual({
            "first_name": "Missing Status",
            "phone": "9000000911",
            "source": self.source.code,
        })
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual(lead.status_id, self.status.id)

    def test_manual_create_rejects_unknown_source_with_source_field_error(self):
        response = self.manual({
            "first_name": "Unknown Source",
            "phone": "9000000912",
            "source": "not-a-project-source",
        })
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("source", response.json()["error"]["details"])


class OtherFormMasterDataReadTests(TestCase):
    """FR-P2-04/API-P2-01: active lookup reads work for non-settings users."""

    def setUp(self):
        self.organization = make_organization("phase4-step9-forms")
        self.project = make_project(self.organization, "MAIN")
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.client = APIClient()

    def assert_active_category_readable(self, category_code):
        category, _ = MasterDataCategory.objects.get_or_create(code=category_code, defaults={"name": category_code})
        MasterData.objects.get_or_create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="active_option",
            defaults={"name": "Active option"},
        )
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/master-data/{category_code}/",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["key"] for row in response.json()["data"]], ["active_option"])

    def test_expense_form_lookup_is_readable_without_settings_view(self):
        self.assert_active_category_readable("expense_category")

    def test_plot_form_lookup_is_readable_without_settings_view(self):
        self.assert_active_category_readable("plot_status")

    def test_site_visit_form_lookup_is_readable_without_settings_view(self):
        self.assert_active_category_readable("site_visit_outcome")

    def test_document_form_lookup_is_readable_without_settings_view(self):
        self.assert_active_category_readable("document_type")
