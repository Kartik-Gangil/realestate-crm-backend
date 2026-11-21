"""Task 11 fix round 3 audit integration tests.

Task/Phase IDs: NFR-P3-02, FR-P3-04, GNFR-07.
These tests deliberately exercise the public API instead of calling services
directly so that request context, transaction handling, and audit ownership are
covered together.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from core.tasks_backend import get_database_backend
from documents.models import CustomerDocument, DocumentCategory
from expenses.models import ApprovalStep, Expense, ExpenseCategory
from inventory.models import Block, Payment, Plot, PlotBooking, PlotHold, Registry
from leads.models import Lead
from organizations.models import Department, OrganizationMembership, OrganizationRole, Permission
from system_settings.models import AuditLog, SystemParameter
from system_settings.parameters import PARAMETER_REGISTRY


class Phase3AuditApiBase(TestCase):
    """Shared API fixture with an organization admin and one project."""

    def setUp(self):
        self.organization = make_organization("phase3-round3-org")
        self.project = make_project(self.organization, "R3")
        self.membership = make_member(self.organization, role="admin", projects=[self.project])
        self.user = self.membership.user
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.slug = self.organization.slug

    def project_headers(self):
        return {"HTTP_X_PROJECT_ID": str(self.project.pk)}

    def audit_rows(self, *, target_type=None, target_id=None, action=None, module=None):
        rows = AuditLog.objects.filter(organization=self.organization, user=self.user)
        if target_type is not None:
            rows = rows.filter(target_type=target_type)
        if target_id is not None:
            rows = rows.filter(target_id=str(target_id))
        if action is not None:
            rows = rows.filter(action=action)
        if module is not None:
            rows = rows.filter(module=module)
        return rows.order_by("id")

    def assert_one_audit(self, *, target_type, target_id, action, before, after, project=None):
        rows = self.audit_rows(target_type=target_type, target_id=target_id, action=action)
        self.assertEqual(rows.count(), 1, list(rows.values("id", "action", "target_type", "target_id")))
        row = rows.get()
        for key, value in (before or {}).items():
            self.assertEqual(row.payload_before.get(key), value)
        for key, value in (after or {}).items():
            self.assertEqual(row.payload_after.get(key), value)
        self.assertEqual(row.organization_id, self.organization.pk)
        self.assertEqual(row.user_id, self.user.pk)
        self.assertEqual(row.project_id, project.pk if project else None)
        return row

    def inventory_fixture(self):
        block = Block.objects.create(
            organization=self.organization, project=self.project, name="Block", code="R3-BLOCK"
        )
        plot = Plot.objects.create(
            organization=self.organization, project=self.project, block=block,
            plot_number="R3-001", size=Decimal("100"), total_price=Decimal("1000"),
            status=Plot.Status.BOOKED,
        )
        lead = Lead.objects.create(
            organization=self.organization, project=self.project,
            first_name="Buyer", last_name="One", phone="9000000011",
        )
        booking = PlotBooking.objects.create(
            organization=self.organization, lead=lead, plot=plot,
            status=PlotBooking.Status.CONFIRMED, final_price=Decimal("1000"), created_by=self.user,
        )
        return block, plot, lead, booking

    def expense_fixture(self, *, status=Expense.Status.DRAFT, submitted_by=None):
        category, _created = ExpenseCategory.objects.get_or_create(
            organization=self.organization, project=self.project, name="Travel",
            defaults={"description": "Round three category"},
        )
        expense = Expense.objects.create(
            organization=self.organization, project=self.project,
            submitted_by=submitted_by or self.user, category=category, amount=Decimal("125.00"),
            description="Round three expense", status=status,
        )
        return category, expense


class Phase3NfrP302UserAndRoleAuditTests(Phase3AuditApiBase):
    """NFR-P3-02: every user and role mutation writes one owned audit row."""

    def test_nfr_p3_02_user_create_has_one_audit_row_with_after_values(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/users/",
            {
                "email": "round3-created@example.test", "temporary_password": "Temp-pass-123",
                "first_name": "Created", "last_name": "Employee", "role": "telecaller",
            }, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        membership = OrganizationMembership.objects.get(
            organization=self.organization, user__email="round3-created@example.test"
        )
        row = self.assert_one_audit(
            target_type="User", target_id=membership.user_id, action="create", before={},
            after={"username": membership.user.username, "email": membership.user.email},
        )
        self.assertEqual(row.organization_id, self.organization.pk)

    def test_nfr_p3_02_user_update_has_real_before_and_after_values(self):
        employee = make_member(self.organization, role="telecaller")
        old_email = employee.user.email
        response = self.client.put(
            f"/api/v1/organizations/{self.slug}/users/{employee.pk}/",
            {"email": "round3-updated@example.test", "first_name": "Updated"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="User", target_id=employee.user_id, action="update",
            before={"email": old_email}, after={"email": "round3-updated@example.test"},
        )

    def test_nfr_p3_02_user_activate_has_one_semantic_audit_row(self):
        employee = make_member(self.organization, role="telecaller")
        employee.is_active = False
        employee.save(update_fields=["is_active"])
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/users/{employee.pk}/activate/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.audit_rows(target_type="OrganizationMembership", target_id=employee.pk, action="activate")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().payload_before.get("is_active"), False)
        self.assertEqual(rows.get().payload_after.get("is_active"), True)

    def test_nfr_p3_02_user_deactivate_has_one_semantic_audit_row(self):
        employee = make_member(self.organization, role="telecaller")
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/users/{employee.pk}/deactivate/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.audit_rows(target_type="OrganizationMembership", target_id=employee.pk, action="deactivate")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().payload_before.get("is_active"), True)
        self.assertEqual(rows.get().payload_after.get("is_active"), False)

    def test_nfr_p3_02_user_role_change_has_one_audit_row(self):
        employee = make_member(self.organization, role="telecaller")
        old_role_id = employee.organization_role_id
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Round Three Reviewer", code="round-three-reviewer"
        )
        response = self.client.put(
            f"/api/v1/organizations/{self.slug}/users/{employee.pk}/",
            {"role_id": role.pk}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.audit_rows(target_type="OrganizationMembership", target_id=employee.pk, action="role_change")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().payload_before.get("organization_role"), old_role_id)
        self.assertEqual(rows.get().payload_after.get("organization_role"), role.pk)

    def test_nfr_p3_02_role_create_has_one_audit_row(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/roles/",
            {"name": "Round Three Role", "code": "round-three-role", "description": "Test role", "permission_ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        role = OrganizationRole.objects.get(organization=self.organization, code="round-three-role")
        row = self.assert_one_audit(
            target_type="OrganizationRole", target_id=role.pk, action="create", before={},
            after={"name": role.name, "code": role.code, "description": role.description},
        )
        self.assertEqual(row.payload_after["organization"], self.organization.pk)

    def test_nfr_p3_02_role_edit_has_real_before_and_after_values(self):
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Before Role", code="before-role", description="Before"
        )
        response = self.client.patch(
            f"/api/v1/organizations/{self.slug}/roles/{role.pk}/",
            {"name": "After Role", "description": "After"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="OrganizationRole", target_id=role.pk, action="update",
            before={"name": "Before Role", "description": "Before"},
            after={"name": "After Role", "description": "After"},
        )

    def test_nfr_p3_02_role_permissions_change_has_one_audit_row(self):
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Permission Role", code="permission-role"
        )
        permission_before, permission_after = list(Permission.objects.order_by("module", "action")[:2])
        role.permissions.add(permission_before)
        response = self.client.put(
            f"/api/v1/organizations/{self.slug}/roles/{role.pk}/permissions/",
            {"permission_ids": [permission_after.pk]}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = self.assert_one_audit(
            target_type="OrganizationRole", target_id=role.pk, action="permissions",
            before={"permissions": sorted([permission_before.code])},
            after={"permissions": sorted([permission_after.code])},
        )
        self.assertEqual(row.details, {"added": sorted([permission_after.code]), "removed": sorted([permission_before.code])})

    def test_nfr_p3_02_role_patch_permissions_audit_uses_permission_codes(self):
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Patch Permission Role", code="patch-permission-role"
        )
        permission_before, permission_after = list(Permission.objects.order_by("module", "action")[:2])
        role.permissions.add(permission_before)
        response = self.client.patch(
            f"/api/v1/organizations/{self.slug}/roles/{role.pk}/",
            {"permission_ids": [permission_after.pk]}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = self.assert_one_audit(
            target_type="OrganizationRole", target_id=role.pk, action="permissions",
            before={"permissions": [permission_before.code]},
            after={"permissions": [permission_after.code]},
        )
        self.assertEqual(row.details, {"added": [permission_after.code], "removed": [permission_before.code]})

    def test_nfr_p3_02_role_delete_has_one_audit_row(self):
        role = OrganizationRole.objects.create(
            organization=self.organization, name="Delete Role", code="delete-role"
        )
        response = self.client.delete(
            f"/api/v1/organizations/{self.slug}/roles/{role.pk}/", {"confirmation": True}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = self.assert_one_audit(
            target_type="OrganizationRole", target_id=role.pk, action="delete",
            before={"name": "Delete Role", "code": "delete-role"}, after={},
        )
        self.assertEqual(row.payload_before["organization"], self.organization.pk)


class Phase3PerAppAuditApiTests(Phase3AuditApiBase):
    """GNFR-07: representative API mutations carry truthful audit context."""

    def test_gnfr_07_payment_update_has_project_audit_context(self):
        _block, _plot, _lead, booking = self.inventory_fixture()
        payment = Payment.objects.create(
            organization=self.organization, booking=booking, payment_id="R3-PAYMENT",
            amount=Decimal("100"), payment_method="cash", status=Payment.Status.PENDING,
            payment_date=date.today(), received_by=self.user,
        )
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/inventory/payments/{payment.pk}/confirm/",
            {}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="Payment", target_id=payment.pk, action="update",
            before={"status": Payment.Status.PENDING}, after={"status": Payment.Status.SUCCESS}, project=self.project,
        )

    def test_gnfr_07_registry_update_has_project_audit_context(self):
        _block, _plot, _lead, booking = self.inventory_fixture()
        registry = Registry.objects.create(organization=self.organization, booking=booking, status=Registry.Status.PENDING)
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/inventory/registries/{registry.pk}/schedule/",
            {}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="Registry", target_id=registry.pk, action="update",
            before={"status": Registry.Status.PENDING}, after={"status": Registry.Status.SCHEDULED}, project=self.project,
        )

    def test_gnfr_07_customer_document_update_has_project_audit_context(self):
        _block, _plot, lead, _booking = self.inventory_fixture()
        category = DocumentCategory.objects.create(organization=self.organization, name="Identity", code="identity")
        document = CustomerDocument.objects.create(
            organization=self.organization, customer=lead, document_category=category,
            document_name="Identity", file=SimpleUploadedFile("identity.pdf", b"pdf", content_type="application/pdf"),
            file_name="identity.pdf", file_size=3, content_type="application/pdf", version=1,
        )
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/documents/{document.pk}/archive/",
            {}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = self.assert_one_audit(
            target_type="CustomerDocument", target_id=document.pk, action="update",
            before={"is_active": True}, after={"is_active": False}, project=self.project,
        )
        self.assertEqual(row.organization_id, self.organization.pk)

    def test_gnfr_07_expense_update_has_project_audit_context(self):
        _category, expense = self.expense_fixture()
        response = self.client.patch(
            f"/api/v1/expenses/{expense.pk}/", {"description": "Updated description"},
            format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="Expense", target_id=expense.pk, action="update",
            before={"description": "Round three expense"}, after={"description": "Updated description"}, project=self.project,
        )

    def test_gnfr_07_system_parameter_update_has_organization_audit_context(self):
        from system_settings.services import ensure_organization_parameter_defaults

        ensure_organization_parameter_defaults(self.organization)
        parameter = SystemParameter.objects.get(
            organization=self.organization, project__isnull=True, parameter_key="auto_logout_minutes"
        )
        old_value = parameter.value
        response = self.client.put(
            f"/api/v1/organizations/{self.slug}/system-parameters/defaults/",
            {"parameter_key": "auto_logout_minutes", "value": old_value + 1}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_one_audit(
            target_type="SystemParameter", target_id=parameter.pk, action="update",
            before={"value": old_value}, after={"value": old_value + 1},
        )

    def test_gnfr_07_department_create_has_organization_audit_context(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/departments/",
            {"name": "Round Three Department", "description": "Department test"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        department = Department.objects.get(organization=self.organization, name="Round Three Department")
        self.assert_one_audit(
            target_type="Department", target_id=department.pk, action="create", before={},
            after={"name": department.name, "description": department.description},
        )

    def test_gnfr_07_expense_approve_and_reject_have_semantic_actions(self):
        submitter = make_member(self.organization, role="telecaller", projects=[self.project])
        _category, approved = self.expense_fixture(status=Expense.Status.PENDING_APPROVAL, submitted_by=submitter.user)
        ApprovalStep.objects.create(expense=approved, step_name="Manager Review")
        response = self.client.post(
            f"/api/v1/expenses/{approved.pk}/approve/", {}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.audit_rows(target_type="Expense", target_id=approved.pk, action="approve").count(), 1)

        _category, rejected = self.expense_fixture(status=Expense.Status.PENDING_APPROVAL, submitted_by=submitter.user)
        ApprovalStep.objects.create(expense=rejected, step_name="Manager Review")
        response = self.client.post(
            f"/api/v1/expenses/{rejected.pk}/reject/", {"reason": "Round three test"},
            format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.audit_rows(target_type="Expense", target_id=rejected.pk, action="reject").count(), 1)


class Phase3BulkAuditApiTests(Phase3AuditApiBase):
    """GNFR-07 bulk mutations each emit one aggregate row with record IDs."""

    def assigned_lead(self):
        employee = make_member(self.organization, role="telecaller", projects=[self.project])
        lead = Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Assigned", phone="9000000022",
            assigned_membership=employee,
        )
        return lead

    def test_gnfr_07_lead_bulk_unassign_has_one_row_with_record_ids(self):
        lead = self.assigned_lead()
        response = self.client.patch(
            f"/api/v1/organizations/{self.slug}/leads/bulk_reset/",
            {"lead_ids": [lead.pk], "reason": "Owner cleared"}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.audit_rows(module="leads", action="bulk_update")
        self.assertEqual(rows.count(), 1)
        self.assertIn(lead.pk, rows.get().details["record_ids"])

    def test_gnfr_07_lead_import_has_one_row_with_record_ids(self):
        csv = SimpleUploadedFile("leads.csv", b"first_name,last_name,phone\nImported,Lead,9000000033\n", content_type="text/csv")
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/leads/import/", {"file": csv},
            format="multipart", **self.project_headers()
        )
        self.assertEqual(response.status_code, 202, response.data)
        get_database_backend().run_once("test-worker")
        imported_ids = list(Lead.objects.filter(project=self.project).values_list("pk", flat=True))
        rows = self.audit_rows(module="leads", action="bulk_create")
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.details["record_ids"], imported_ids)
        self.assertEqual(row.project_id, self.project.pk)

    def test_gnfr_07_document_new_version_has_one_archive_bulk_row(self):
        _block, _plot, lead, _booking = self.inventory_fixture()
        category = DocumentCategory.objects.create(organization=self.organization, name="Identity", code="identity")
        CustomerDocument.objects.create(
            organization=self.organization, customer=lead, document_category=category,
            document_name="Identity", file=SimpleUploadedFile("old.pdf", b"old", content_type="application/pdf"),
            file_name="old.pdf", file_size=3, content_type="application/pdf", version=1,
        )
        upload = SimpleUploadedFile("new.pdf", b"%PDF-1.4\nround-three", content_type="application/pdf")
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/documents/",
            {"customer": lead.pk, "document_category": category.pk, "document_name": "Identity", "file": upload},
            format="multipart", **self.project_headers()
        )
        self.assertEqual(response.status_code, 201, response.data)
        rows = self.audit_rows(module="documents", action="bulk_update")
        self.assertEqual(rows.count(), 1)
        self.assertTrue(rows.get().details["record_ids"])

    def test_gnfr_07_plot_hold_release_has_one_row_with_record_ids(self):
        _block, plot, _lead, _booking = self.inventory_fixture()
        plot.status = Plot.Status.HOLD
        plot.save(update_fields=["status"])
        hold = PlotHold.objects.create(plot=plot, action_type=PlotHold.ActionType.HOLD, reason="Round three")
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/inventory/plots/{plot.pk}/release/",
            {"reason": "Round three release"}, format="json", **self.project_headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.audit_rows(module="inventory", action="bulk_update")
        self.assertEqual(rows.count(), 1)
        self.assertIn(hold.pk, rows.get().details["record_ids"])

    def test_gnfr_07_project_default_copy_has_settings_rows_with_record_ids(self):
        from system_settings.services import ensure_organization_parameter_defaults

        ensure_organization_parameter_defaults(self.organization)
        response = self.client.post(
            f"/api/v1/organizations/{self.slug}/inventory/projects/",
            {"name": "Round Three Project", "code": "R3-COPY"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        project = self.organization.inventory_projects.get(code="R3-COPY")
        rows = AuditLog.objects.filter(
            organization=self.organization, project=project, module="settings", action="bulk_create"
        )
        self.assertGreater(rows.count(), 0)
        for row in rows:
            self.assertTrue(row.details["record_ids"])

