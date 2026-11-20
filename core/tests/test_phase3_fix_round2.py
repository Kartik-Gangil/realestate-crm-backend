from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, TransactionTestCase
from rest_framework.test import APIClient

from core.audit_context import get_current_request
from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from inventory.models import Project
from leads.models import Lead
from organizations.models import OrganizationRole, ProjectAssignment
from system_settings.models import AuditLog


class RealAuditModelCoverageTests(TestCase):
    """FR-P3-04/DM-P3-03: every first-party model has an audit disposition."""

    def test_every_first_party_model_is_registered_or_explicitly_excluded(self):
        from core.audit_registry import AUDIT_MODEL_LABELS, EXCLUDED_MODEL_LABELS

        first_party_apps = {
            "core", "documents", "expenses", "inventory", "leads",
            "organizations", "system_settings", "users",
        }
        expected = {
            f"{model._meta.app_label}.{model.__name__}"
            for model in apps.get_models()
            if model._meta.app_label in first_party_apps
        }
        expected.add("auth.User")
        covered = set(AUDIT_MODEL_LABELS) | set(EXCLUDED_MODEL_LABELS)
        self.assertEqual(expected - covered, set())
        self.assertEqual(set(AUDIT_MODEL_LABELS) & set(EXCLUDED_MODEL_LABELS), set())


class WriteTransactionTests(TransactionTestCase):
    """FR-P3-04: API mutations are atomic, reads are not wrapped."""

    def setUp(self):
        self.organization = make_organization("round2-transaction-org")
        self.project = make_project(self.organization, "ROUND2")
        self.member = make_member(self.organization, role="admin", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.member.user)

    def test_lead_post_returns_500_and_rolls_back_when_audit_write_fails(self):
        self.client.raise_request_exception = False
        with patch("system_settings.models.AuditLog.objects.create", side_effect=RuntimeError("audit failure")):
            response = self.client.post(
                f"/api/v1/organizations/{self.organization.slug}/leads/",
                {"first_name": "Atomic", "last_name": "Failure", "phone": "0000000000", "source": "website"},
                format="json",
                **project_request_kwargs(self.project),
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(Lead.objects.filter(first_name="Atomic").exists())

    def test_audit_middleware_wraps_api_writes_but_not_reads(self):
        from core.middleware.audit_context import AuditContextMiddleware
        from django.db import connection

        seen = []

        def get_response(request):
            seen.append(connection.in_atomic_block)
            return object()

        middleware = AuditContextMiddleware(get_response)
        factory = RequestFactory()
        middleware(factory.post("/api/v1/organizations/round2-transaction-org/leads/"))
        middleware(factory.get("/api/v1/organizations/round2-transaction-org/leads/"))
        self.assertEqual(seen, [True, False])


class AuditLogImmutabilityTests(TestCase):
    def test_audit_log_bulk_update_is_blocked(self):
        row = AuditLog.objects.create(module="settings", action="create")
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(pk=row.pk).update(details={"changed": True})

    def test_deleted_organization_and_project_keep_ids_in_audit_details(self):
        organization = make_organization("round2-delete-org")
        project = make_project(organization, "DELETE-ME")
        row = AuditLog.objects.create(
            organization=organization,
            project=project,
            module="inventory",
            action="update",
            details={"seed": True},
        )

        project_id = project.pk
        organization_id = organization.pk
        project.delete()
        row.refresh_from_db()
        self.assertIsNone(row.project_id)
        project_delete = AuditLog.objects.filter(target_type="Project", target_id=str(project_id), action="delete").latest("pk")
        self.assertEqual(project_delete.details["deleted_project_id"], project_id)

        organization.delete()
        row.refresh_from_db()
        self.assertIsNone(row.organization_id)
        organization_delete = AuditLog.objects.filter(target_type="Organization", target_id=str(organization_id), action="delete").latest("pk")
        self.assertEqual(organization_delete.details["deleted_organization_id"], organization_id)


class BulkAuditTests(TestCase):
    def setUp(self):
        self.organization = make_organization("round2-bulk-org")
        self.project = make_project(self.organization, "BULK")
        self.member = make_member(self.organization, role="admin", projects=[self.project])
        self.request = RequestFactory().patch(f"/api/v1/organizations/{self.organization.slug}/users/")
        self.request.user = self.member.user
        self.client = APIClient()
        self.client.force_authenticate(self.member.user)

    def test_project_assignment_bulk_delete_writes_one_aggregate_row(self):
        assignment = ProjectAssignment.objects.get(membership=self.member, project=self.project)
        from organizations.employee_views import _sync_project_assignments

        _sync_project_assignments(self.member, [], self.member.user)

        rows = AuditLog.objects.filter(module="employees", action="bulk_delete")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().details["record_ids"], [assignment.pk])

    def test_project_assignment_bulk_update_writes_one_aggregate_row(self):
        assignment = ProjectAssignment.objects.get(membership=self.member, project=self.project)
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Bulk Update Role", code="bulk-update-role"
        )
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/users/{self.member.pk}/",
            {"role_id": role.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        rows = AuditLog.objects.filter(module="employees", action="bulk_update")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().details["record_ids"], [assignment.pk])

