from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from leads.models import Lead
from documents.models import DocumentCategory
from expenses.models import ExpenseCategory
from inventory.models import Block
from organizations.project_scope import reset_current_project, set_current_project
from system_settings.models import AuditLog, MasterData, SystemParameter

from .models import AttendanceRecord, Organization, OrganizationMembership, Project


class Phase0ProjectFoundationApiTests(TestCase):
    """PHASE 0: FR-P0-01/02/05/06 and API-P0-01/02/03."""

    def setUp(self):
        self.client = APIClient()
        users = get_user_model().objects
        self.admin = users.create_user(
            username="admin@example.test",
            email="admin@example.test",
            password="Valid-password-1!",
        )
        self.member = users.create_user(
            username="member@example.test",
            email="member@example.test",
            password="Valid-password-1!",
        )
        self.outsider = users.create_user(
            username="outsider@example.test",
            email="outsider@example.test",
            password="Valid-password-1!",
        )
        self.organization = Organization.objects.create(
            name="Acme Realty",
            slug="acme-realty",
            code="ORG-ACME",
            status=Organization.Status.ACTIVE,
        )
        self.foreign_organization = Organization.objects.create(
            name="Foreign Realty",
            slug="foreign-realty",
            code="ORG-FOREIGN",
            status=Organization.Status.ACTIVE,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Acme Greens",
            code="PRJ-ACME",
            description="Primary project",
        )
        self.foreign_project = Project.objects.create(
            organization=self.foreign_organization,
            name="Foreign Greens",
            code="PRJ-FOREIGN",
        )

    def assert_success_envelope(self, response):
        self.assertTrue(response.data["success"])
        self.assertIsNone(response.data["error"])
        self.assertIn("timestamp", response.data["meta"])
        return response.data["data"]

    def test_api_p0_01_and_p0_02_list_only_assigned_organizations_and_projects(self):
        self.client.force_authenticate(self.member)

        organizations_response = self.client.get("/api/v1/organizations/")
        projects_response = self.client.get("/api/v1/projects/")

        self.assertEqual(organizations_response.status_code, 200)
        self.assertEqual(projects_response.status_code, 200)
        organizations = self.assert_success_envelope(organizations_response)
        projects = self.assert_success_envelope(projects_response)
        self.assertEqual([item["code"] for item in organizations], ["ORG-ACME"])
        self.assertEqual([item["code"] for item in projects], ["PRJ-ACME"])

    def test_ec_p0_01_user_with_zero_assignments_gets_empty_lists(self):
        self.client.force_authenticate(self.outsider)

        organizations = self.assert_success_envelope(self.client.get("/api/v1/organizations/"))
        projects = self.assert_success_envelope(self.client.get("/api/v1/projects/"))

        self.assertEqual(organizations, [])
        self.assertEqual(projects, [])

    def test_fr_p0_06_admin_can_create_project_and_mutation_is_audited(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            "/api/v1/projects/",
            {
                "organization_id": self.organization.id,
                "name": "Acme Enclave",
                "code": "PRJ-ENCLAVE",
                "description": "Phase two",
            },
            format="json",
            REMOTE_ADDR="203.0.113.20",
        )

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)
        self.assertEqual(data["status"], Project.Status.ACTIVE)
        project = Project.objects.get(code="PRJ-ENCLAVE")
        audit = AuditLog.objects.get(module="projects", action="create", target_id=str(project.id))
        self.assertEqual(audit.ip_address, "203.0.113.20")
        self.assertEqual(audit.details["payload_before"], None)
        self.assertEqual(audit.details["payload_after"]["code"], "PRJ-ENCLAVE")

    def test_fr_p0_06_non_admin_cannot_create_project(self):
        self.client.force_authenticate(self.member)

        response = self.client.post(
            "/api/v1/projects/",
            {
                "organization_id": self.organization.id,
                "name": "Blocked Project",
                "code": "PRJ-BLOCKED",
                "description": "",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Project.objects.filter(code="PRJ-BLOCKED").exists())

    def test_fr_p0_01_admin_can_retrieve_update_and_soft_delete_project(self):
        self.client.force_authenticate(self.admin)
        headers = {"HTTP_X_PROJECT_ID": self.project.code}

        detail = self.client.get(f"/api/v1/projects/{self.project.id}/", **headers)
        updated = self.client.patch(
            f"/api/v1/projects/{self.project.id}/",
            {"name": "Acme Greens Updated"},
            format="json",
            **headers,
        )
        deleted = self.client.delete(f"/api/v1/projects/{self.project.id}/", **headers)

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.assert_success_envelope(updated)["name"], "Acme Greens Updated")
        self.assertEqual(deleted.status_code, 204)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.INACTIVE)

    def test_ec_p0_02_invalid_or_stale_project_context_blocks_mutation(self):
        self.client.force_authenticate(self.admin)
        self.project.status = Project.Status.INACTIVE
        self.project.save(update_fields=["status"])

        response = self.client.patch(
            f"/api/v1/projects/{self.project.id}/",
            {"name": "Must Not Persist"},
            format="json",
            HTTP_X_PROJECT_ID=self.project.code,
        )

        self.assertEqual(response.status_code, 409)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Acme Greens")
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "invalid_project_context")

    def test_project_code_is_unique_within_organization(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            "/api/v1/projects/",
            {
                "organization_id": self.organization.id,
                "name": "Duplicate",
                "code": self.project.code,
                "description": "",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.filter(organization=self.organization).count(), 1)


class Phase0HealthEndpointsTests(TestCase):
    """FR-P0-05: liveness is process-only; readiness checks dependencies."""

    def test_healthz_is_public_and_reports_liveness(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ok")

    def test_readyz_is_public_and_reports_database_readiness(self):
        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ready")

    @patch("organizations.health.connection.ensure_connection", side_effect=RuntimeError("database unavailable"))
    def test_readyz_returns_503_when_database_is_unavailable(self, _ensure_connection):
        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["error"]["code"], "service_not_ready")


class Phase0ProjectContextMiddlewareTests(TestCase):
    """FR-P0-02/GNFR-06: versioned tenant APIs require a valid project context."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="context@example.test",
            email="context@example.test",
            password="Valid-password-1!",
        )
        self.organization = Organization.objects.create(
            name="Context Org", slug="context-org", code="ORG-CONTEXT"
        )
        self.other_organization = Organization.objects.create(
            name="Other Org", slug="other-org", code="ORG-OTHER"
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization, name="Current", code="PRJ-CURRENT"
        )
        self.other_project = Project.objects.create(
            organization=self.other_organization, name="Other", code="PRJ-OTHER"
        )
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.url = "/api/v1/organizations/context-org/my-tab-permissions/"

    def test_missing_project_header_is_blocked_before_the_controller(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "project_context_required")

    def test_cross_organization_project_header_is_blocked(self):
        response = self.client.get(self.url, HTTP_X_PROJECT_ID=self.other_project.code)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid_project_context")

    def test_inactive_project_header_is_blocked(self):
        self.project.status = Project.Status.INACTIVE
        self.project.save(update_fields=["status"])

        response = self.client.get(self.url, HTTP_X_PROJECT_ID=self.project.code)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid_project_context")

    def test_valid_project_header_allows_the_versioned_request(self):
        response = self.client.get(self.url, HTTP_X_PROJECT_ID=self.project.code)

        self.assertEqual(response.status_code, 200)


class Phase0LeadRowIsolationTests(TestCase):
    """FR-P0-02/GNFR-06: rows in one organization remain isolated by project."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="row-scope@example.test",
            email="row-scope@example.test",
            password="Valid-password-1!",
        )
        self.organization = Organization.objects.create(
            name="Scoped Org", slug="scoped-org", code="ORG-SCOPED"
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project_a = Project.objects.create(
            organization=self.organization, name="Project A", code="PRJ-A"
        )
        self.project_b = Project.objects.create(
            organization=self.organization, name="Project B", code="PRJ-B"
        )
        self.lead_a = Lead.objects.create(
            organization=self.organization,
            project=self.project_a,
            first_name="Project A Lead",
            phone="9000000001",
        )
        self.lead_b = Lead.objects.create(
            organization=self.organization,
            project=self.project_b,
            first_name="Project B Lead",
            phone="9000000002",
        )
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.list_url = "/api/v1/organizations/scoped-org/leads/"

    def test_list_and_detail_do_not_leak_rows_from_another_project(self):
        response = self.client.get(self.list_url, HTTP_X_PROJECT_ID=self.project_a.code)
        hidden_detail = self.client.get(
            f"{self.list_url}{self.lead_b.id}/",
            HTTP_X_PROJECT_ID=self.project_a.code,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.lead_a.id])
        self.assertEqual(hidden_detail.status_code, 404)

    def test_created_row_is_bound_to_resolved_project(self):
        response = self.client.post(
            self.list_url,
            {"first_name": "New Scoped Lead", "phone": "9000000003", "source": "website"},
            format="json",
            HTTP_X_PROJECT_ID=self.project_a.code,
        )

        self.assertEqual(response.status_code, 201)
        lead = Lead.all_objects.get(pk=response.data["id"])
        self.assertEqual(lead.project, self.project_a)

    def test_each_project_sees_its_own_rows(self):
        response = self.client.get(self.list_url, HTTP_X_PROJECT_ID=self.project_b.code)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.lead_b.id])


class Phase0CrossDomainRowIsolationTests(TestCase):
    """FR-P0-02/GNFR-06: core domain managers enforce the active project boundary."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Cross Domain Org", slug="cross-domain", code="ORG-CROSS"
        )
        self.project_a = Project.objects.create(
            organization=self.organization, name="Project A", code="CROSS-A"
        )
        self.project_b = Project.objects.create(
            organization=self.organization, name="Project B", code="CROSS-B"
        )

    def assert_manager_isolates_projects(self, model, create_values):
        first = model.all_objects.create(project=self.project_a, **create_values("A"))
        second = model.all_objects.create(project=self.project_b, **create_values("B"))

        token = set_current_project(self.project_a.id)
        try:
            visible_ids = list(model.objects.values_list("id", flat=True))
            created = model.objects.create(**create_values("New"))
        finally:
            reset_current_project(token)

        self.assertEqual(visible_ids, [first.id])
        self.assertEqual(created.project, self.project_a)
        self.assertNotEqual(created.id, second.id)

    def test_inventory_rows_are_project_scoped(self):
        self.assert_manager_isolates_projects(
            Block,
            lambda suffix: {
                "organization": self.organization,
                "name": f"Block {suffix}",
                "code": f"BLOCK-{suffix}",
            },
        )

    def test_document_rows_are_project_scoped(self):
        self.assert_manager_isolates_projects(
            DocumentCategory,
            lambda suffix: {
                "organization": self.organization,
                "name": f"Document {suffix}",
                "code": f"DOC-{suffix}",
            },
        )

    def test_expense_rows_are_project_scoped(self):
        self.assert_manager_isolates_projects(
            ExpenseCategory,
            lambda suffix: {
                "organization": self.organization,
                "name": f"Expense {suffix}",
            },
        )

    def test_project_scoped_codes_and_names_may_repeat_across_projects(self):
        Block.all_objects.create(
            organization=self.organization, project=self.project_a, name="Main", code="MAIN"
        )
        Block.all_objects.create(
            organization=self.organization, project=self.project_b, name="Main", code="MAIN"
        )
        DocumentCategory.all_objects.create(
            organization=self.organization, project=self.project_a, name="PAN", code="pan"
        )
        DocumentCategory.all_objects.create(
            organization=self.organization, project=self.project_b, name="PAN", code="pan"
        )
        ExpenseCategory.all_objects.create(
            organization=self.organization, project=self.project_a, name="Travel"
        )
        ExpenseCategory.all_objects.create(
            organization=self.organization, project=self.project_b, name="Travel"
        )

        self.assertEqual(Block.all_objects.filter(code="MAIN").count(), 2)
        self.assertEqual(DocumentCategory.all_objects.filter(code="pan").count(), 2)
        self.assertEqual(ExpenseCategory.all_objects.filter(name="Travel").count(), 2)


class Phase0HrAndSettingsIsolationTests(TestCase):
    """FR-P0-02/GNFR-06: operational HR and consumed settings are project scoped."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="hr-scope@example.test", email="hr-scope@example.test", password="password"
        )
        self.organization = Organization.objects.create(
            name="HR Scope Org", slug="hr-scope", code="ORG-HR-SCOPE"
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project_a = Project.objects.create(
            organization=self.organization, name="Project A", code="HR-A"
        )
        self.project_b = Project.objects.create(
            organization=self.organization, name="Project B", code="HR-B"
        )

    def test_attendance_rows_are_isolated_and_same_day_is_valid_per_project(self):
        first = AttendanceRecord.all_objects.create(
            organization=self.organization,
            project=self.project_a,
            employee=self.membership,
            attendance_date="2026-09-18",
        )
        AttendanceRecord.all_objects.create(
            organization=self.organization,
            project=self.project_b,
            employee=self.membership,
            attendance_date="2026-09-18",
        )

        token = set_current_project(self.project_a.id)
        try:
            visible_ids = list(AttendanceRecord.objects.values_list("id", flat=True))
        finally:
            reset_current_project(token)

        self.assertEqual(visible_ids, [first.id])

    def test_master_data_and_parameters_are_isolated_with_project_local_keys(self):
        for project in (self.project_a, self.project_b):
            MasterData.all_objects.create(
                organization=self.organization,
                project=project,
                master_type="lead_status",
                code="new",
                name="New",
            )
            SystemParameter.all_objects.create(
                organization=self.organization,
                project=project,
                parameter_key="reminder-days",
                parameter_name="Reminder days",
                value=3,
                data_type=SystemParameter.DataType.INTEGER,
            )

        token = set_current_project(self.project_b.id)
        try:
            master_projects = list(MasterData.objects.values_list("project_id", flat=True))
            parameter_projects = list(SystemParameter.objects.values_list("project_id", flat=True))
        finally:
            reset_current_project(token)

        self.assertEqual(master_projects, [self.project_b.id])
        self.assertEqual(parameter_projects, [self.project_b.id])
