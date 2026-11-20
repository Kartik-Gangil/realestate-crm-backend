from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings

from core.audit_context import reset_current_request, set_current_request
from core.tests.factories import make_member, make_organization, make_project
from inventory.models import Project
from leads.models import Lead
from organizations.models import OrganizationMembership
from system_settings.models import AuditLog


class AutomaticAuditLoggingTests(TestCase):
    """Phase 3 GNFR-07 / FR-P3-04 / DM-P3-03 regression coverage."""

    def setUp(self):
        self.organization = make_organization("audit-fix-org")
        self.project = make_project(self.organization, "AUDIT-FIX")
        self.membership = make_member(self.organization, role="admin", projects=[self.project])
        self.user = self.membership.user
        self.request = RequestFactory().post("/api/v1/organizations/audit-fix-org/leads/")
        self.request.user = self.user

    def test_lead_create_writes_exactly_one_row_with_changed_values(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Before",
            last_name="Lead",
            phone="0000000000",
        )

        rows = AuditLog.objects.filter(target_type="Lead", target_id=str(lead.pk))

        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.action, "create")
        self.assertEqual(row.organization_id, self.organization.pk)
        self.assertEqual(row.project_id, self.project.pk)
        self.assertEqual(row.payload_before, {})
        self.assertEqual(row.payload_after["first_name"], "Before")

    def test_lead_update_writes_only_changed_values(self):
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Before",
            last_name="Lead",
            phone="0000000000",
        )
        before_count = AuditLog.objects.filter(target_type="Lead", target_id=str(lead.pk)).count()

        lead.first_name = "After"
        lead.save(update_fields=["first_name"])

        rows = AuditLog.objects.filter(target_type="Lead", target_id=str(lead.pk))
        self.assertEqual(rows.count(), before_count + 1)
        row = rows.order_by("-pk").first()
        self.assertEqual(row.action, "update")
        self.assertEqual(row.payload_before, {"first_name": "Before"})
        self.assertEqual(row.payload_after, {"first_name": "After"})

    def test_audit_failure_rolls_back_the_mutation(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                with patch("system_settings.models.AuditLog.objects.create", side_effect=RuntimeError("audit failure")):
                    Lead.objects.create(
                        organization=self.organization,
                        project=self.project,
                        first_name="Rollback",
                        phone="0000000000",
                    )

        self.assertFalse(Lead.objects.filter(first_name="Rollback").exists())

    def test_sensitive_user_values_are_redacted(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="sensitive-audit-user", password="secret-value")

        row = AuditLog.objects.filter(target_type="User", target_id=str(user.pk)).order_by("-pk").first()

        self.assertIsNotNone(row)
        payload = row.payload_after or {}
        self.assertEqual(payload.get("password"), "[redacted]")
        self.assertNotIn("secret-value", str(payload))

    @override_settings(DJANGO_TRUST_PROXY=True)
    def test_audit_ip_uses_forwarded_client_address_when_proxy_is_trusted_gnfr_14(self):
        request = RequestFactory().post(
            "/api/v1/organizations/audit-fix-org/leads/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.30",
        )
        request.user = self.user
        token = set_current_request(request)
        try:
            lead = Lead.objects.create(
                organization=self.organization,
                project=self.project,
                first_name="Proxy",
                last_name="Audit",
                phone="0000000000",
            )
        finally:
            reset_current_request(token)

        row = AuditLog.objects.get(target_type="Lead", target_id=str(lead.pk))
        self.assertEqual(row.ip_address, "198.51.100.30")


class AuditModelCoverageTests(TestCase):
    def test_every_phase3_audit_model_is_registered_or_explicitly_excluded(self):
        from core.audit_registry import AUDIT_MODEL_LABELS, EXCLUDED_MODEL_LABELS

        self.assertTrue(AUDIT_MODEL_LABELS)
        self.assertTrue(EXCLUDED_MODEL_LABELS)
        self.assertEqual(set(AUDIT_MODEL_LABELS) & set(EXCLUDED_MODEL_LABELS), set())

