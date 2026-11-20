"""Phase 16 regression tests for the expense workflow."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from core.tests.samples import SAMPLE_PDF
from inventory.models import Project
from system_settings.models import SystemParameter

from organizations.models import OrganizationMembership, OrganizationRole, Permission, ProjectAssignment
from .models import ApprovalStep, Expense, ExpenseCategory
from django.core.files.uploadedfile import SimpleUploadedFile


class ExpensePhase16WorkflowTests(TestCase):
    def setUp(self):
        self.organization = make_organization("phase-16-org")
        self.project = make_project(self.organization, "P16")
        self.other_project = make_project(self.organization, "P16-OTHER")
        self.employee_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.employee = self.employee_membership.user
        self.manager = self.manager_membership.user
        self.admin = self.admin_membership.user
        ProjectAssignment.objects.create(
            membership=self.employee_membership,
            project=self.other_project,
            role=self.employee_membership.organization_role,
        )

        def permissions(codes):
            return [
                Permission.objects.get_or_create(
                    module=module, action=action, defaults={"name": f"{module}.{action}"}
                )[0]
                for module, action in (permission.split(".", 1) for permission in codes)
            ]

        self.employee_membership.organization_role.permissions.add(*permissions([
            "expenses.view_own", "expenses.edit_own", "expenses.submit", "expenses.add",
        ]))
        self.manager_membership.organization_role.permissions.add(*permissions([
            "expenses.view_team", "expenses.approve", "expenses.reject",
        ]))
        self.category = ExpenseCategory.objects.create(organization=self.organization, project=self.project, name="Travel")
        self.client = APIClient()

    def auth(self, user, project=None):
        self.client.force_authenticate(user)
        return {"HTTP_X_PROJECT_ID": str((project or self.project).id)}

    def receipt(self):
        return SimpleUploadedFile("receipt.pdf", SAMPLE_PDF, content_type="application/pdf")

    def create_submitted(self, amount="125.00"):
        response = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": amount,
                "description": "Submitted taxi",
                "date": "2026-09-28",
                "action": "submit",
                "receipt": self.receipt(),
            },
            format="multipart",
            **self.auth(self.employee),
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Expense.objects.get(pk=response.data["data"]["id"])

    def test_employee_can_submit_manager_can_approve_and_reject_requires_reason(self):
        draft = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": "125.00",
                "description": "Draft taxi",
                "date": "2026-09-28",
                "action": "draft",
            },
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(draft.status_code, 201, draft.data)
        self.assertEqual(draft.data["data"]["status"], Expense.Status.DRAFT)

        submitted = self.create_submitted()
        self.assertEqual(submitted.status, Expense.Status.PENDING_APPROVAL)

        approved = self.client.post(f"/api/expenses/{submitted.id}/approve/", {}, format="json", **self.auth(self.manager))
        self.assertEqual(approved.status_code, 200, approved.data)
        submitted.refresh_from_db()
        self.assertEqual(submitted.status, Expense.Status.APPROVED)

        rejected = self.create_submitted()
        no_reason = self.client.post(f"/api/expenses/{rejected.id}/reject/", {}, format="json", **self.auth(self.manager))
        self.assertEqual(no_reason.status_code, 400)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Expense.Status.PENDING_APPROVAL)

        with_reason = self.client.post(
            f"/api/expenses/{rejected.id}/reject/",
            {"reason": "Receipt is not readable."},
            format="json",
            **self.auth(self.manager),
        )
        self.assertEqual(with_reason.status_code, 200, with_reason.data)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Expense.Status.REJECTED)
        self.assertEqual(with_reason.data["data"]["rejection_reason"], "Receipt is not readable.")

    def test_telecaller_add_permission_does_not_grant_org_wide_expense_visibility(self):
        other_user = get_user_model().objects.create_user(
            username="other-expense-employee", email="other-expense@example.com"
        )
        other_role = OrganizationRole.objects.create(
            organization=self.organization, name="Other Telecaller", code="other-telecaller"
        )
        other_role.permissions.set([
            Permission.objects.get_or_create(
                module="expenses", action=action, defaults={"name": f"expenses.{action}"}
            )[0]
            for action in ("view_own", "edit_own", "submit")
        ])
        OrganizationMembership.objects.create(
            organization=self.organization, user=other_user, role="telecaller", organization_role=other_role
        )
        other_membership = OrganizationMembership.objects.get(user=other_user, organization=self.organization)
        ProjectAssignment.objects.create(membership=other_membership, project=self.project, role=other_role)
        Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=other_user,
            paid_by=self.employee,
            category=self.category,
            amount="200.00",
            description="Another employee expense",
        )

        response = self.client.get("/api/expenses/", format="json", **self.auth(self.employee))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["results"], [])

    def test_expense_visibility_uses_expense_permissions_not_data_scope(self):
        viewer = get_user_model().objects.create_user(
            username="expense-viewer", email="expense-viewer@example.com"
        )
        viewer_role = OrganizationRole.objects.create(
            organization=self.organization, name="Expense Viewer", code="expense-viewer"
        )
        viewer_role.permissions.add(
            Permission.objects.get_or_create(
                module="expenses", action="view", defaults={"name": "expenses.view"}
            )[0]
        )
        viewer_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=viewer,
            role="telecaller",
            organization_role=viewer_role,
        )
        ProjectAssignment.objects.create(membership=viewer_membership, project=self.project, role=viewer_role)
        own_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=viewer,
            category=self.category,
            amount="100.00",
            description="Viewer expense",
        )
        other_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount="150.00",
            description="Other expense",
        )

        visible_by_scope = {}
        for scope in (
            OrganizationMembership.AccessScope.OWN,
            OrganizationMembership.AccessScope.ALL,
        ):
            viewer_membership.access_scope = scope
            viewer_membership.save(update_fields=["access_scope"])
            response = self.client.get(
                "/api/expenses/",
                format="json",
                **self.auth(viewer),
            )
            self.assertEqual(response.status_code, 200, response.data)
            visible_by_scope[scope] = {item["id"] for item in response.data["data"]["results"]}

        self.assertEqual(visible_by_scope[OrganizationMembership.AccessScope.OWN], {
            own_expense.id, other_expense.id,
        })
        self.assertEqual(visible_by_scope[OrganizationMembership.AccessScope.ALL], {
            own_expense.id, other_expense.id,
        })

    def test_legacy_pending_expense_without_manager_step_can_be_approved(self):
        expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("125.00"),
            description="Legacy pending expense",
            status=Expense.Status.PENDING_APPROVAL,
        )

        response = self.client.post(
            f"/api/expenses/{expense.id}/approve/",
            {},
            format="json",
            **self.auth(self.manager),
        )

        self.assertEqual(response.status_code, 200, response.data)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.APPROVED)
        manager_step = expense.approval_steps.get(step_name="Manager Review")
        self.assertEqual(manager_step.status, ApprovalStep.Status.DONE)
        self.assertEqual(manager_step.actor_id, self.manager.id)

    def test_task_p16_001_allows_submission_without_receipt_above_configured_threshold(self):
        SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="expense_receipt_threshold",
            parameter_name="Expense receipt threshold",
            value="1000",
            data_type=SystemParameter.DataType.DECIMAL,
        )
        response = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": "1001.00",
                "description": "Threshold test",
                "date": "2026-09-28",
                "action": "submit",
            },
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], Expense.Status.PENDING_APPROVAL)

    def test_api_p17_03_reports_export_returns_xlsx_and_pdf_for_export_permission(self):
        export_permission = Permission.objects.get_or_create(
            module="reports", action="export", defaults={"name": "reports.export"}
        )[0]
        self.manager_membership.organization_role.permissions.add(export_permission)

        xlsx = self.client.get(
            "/api/reports/export/", {"format": "xlsx"}, format="json", **self.auth(self.manager)
        )
        self.assertEqual(xlsx.status_code, 200, xlsx.data if hasattr(xlsx, "data") else xlsx.content)
        self.assertEqual(
            xlsx["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(xlsx.content.startswith(b"PK"))

        pdf = self.client.get(
            "/api/reports/export/", {"format": "pdf"}, format="json", **self.auth(self.manager)
        )
        self.assertEqual(pdf.status_code, 200, pdf.data if hasattr(pdf, "data") else pdf.content)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_api_p17_03_reports_export_requires_export_permission(self):
        response = self.client.get(
            "/api/reports/export/", {"format": "xlsx"}, format="json", **self.auth(self.manager)
        )

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["detail"], "Export permission is required.")

    def test_approved_expense_cannot_be_edited_and_project_scope_is_enforced(self):
        expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("100.00"),
            description="Approved expense",
            status=Expense.Status.APPROVED,
        )
        edit = self.client.patch(
            f"/api/expenses/{expense.id}/",
            {"description": "Changed"},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(edit.status_code, 400)

        other_project = self.client.get(
            f"/api/expenses/{expense.id}/",
            **self.auth(self.employee, self.other_project),
        )
        self.assertEqual(other_project.status_code, 404)

    def test_reject_and_mark_paid_require_their_explicit_permissions(self):
        user_model = get_user_model()
        rejector = user_model.objects.create_user(username="expense-rejector", email="rejector@example.com")
        reject_permission, _ = Permission.objects.get_or_create(
            module="expenses", action="reject", defaults={"name": "Reject expenses"}
        )
        rejector_role = OrganizationRole.objects.create(
            organization=self.organization, name="Expense Rejector", code="expense-rejector"
        )
        rejector_role.permissions.add(reject_permission)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=rejector,
            role="expense-rejector",
            organization_role=rejector_role,
        )
        rejector_membership = OrganizationMembership.objects.get(user=rejector, organization=self.organization)
        ProjectAssignment.objects.create(membership=rejector_membership, project=self.project, role=rejector_role)

        submitted = self.create_submitted()
        denied_reject = self.client.post(
            f"/api/expenses/{submitted.id}/reject/",
            {"reason": "Not eligible."},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(denied_reject.status_code, 403)

        allowed_reject = self.client.post(
            f"/api/expenses/{submitted.id}/reject/",
            {"reason": "Not eligible."},
            format="json",
            **self.auth(rejector),
        )
        self.assertEqual(allowed_reject.status_code, 200, allowed_reject.data)

        paid_expense = self.create_submitted()
        approved = self.client.post(
            f"/api/expenses/{paid_expense.id}/approve/",
            {},
            format="json",
            **self.auth(self.manager),
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        processor = user_model.objects.create_user(username="expense-processor", email="processor@example.com")
        mark_paid_permission, _ = Permission.objects.get_or_create(
            module="expenses", action="mark_paid", defaults={"name": "Mark expenses as paid"}
        )
        processor_role = OrganizationRole.objects.create(
            organization=self.organization, name="Expense Processor", code="expense-processor"
        )
        processor_role.permissions.add(mark_paid_permission)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=processor,
            role="expense-processor",
            organization_role=processor_role,
        )
        processor_membership = OrganizationMembership.objects.get(user=processor, organization=self.organization)
        ProjectAssignment.objects.create(membership=processor_membership, project=self.project, role=processor_role)

        denied_payment = self.client.post(
            f"/api/expenses/{paid_expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(denied_payment.status_code, 403)

        allowed_payment = self.client.post(
            f"/api/expenses/{paid_expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash", "paid_by": ""},
            format="json",
            **self.auth(processor),
        )
        self.assertEqual(allowed_payment.status_code, 201, allowed_payment.data)
        self.assertEqual(allowed_payment.data["data"]["paid_by"]["id"], processor.id)

    def test_org_scoped_expense_creation_without_active_project_returns_validation_error_fr_p0_02_g1_item_5(self):
        category = ExpenseCategory.objects.create(
            organization=self.organization,
            project=None,
            name="Office",
        )
        self.client.force_authenticate(self.employee)

        response = self.client.post(
            "/api/expenses/",
            {
                "category": category.id,
                "amount": "125.00",
                "description": "Office supplies",
                "date": "2026-09-28",
                "action": "draft",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("project", response.data)

    def test_mark_paid_uses_authenticated_actor_when_paid_by_is_blank(self):
        processor = get_user_model().objects.create_user(
            username="blank-paid-by-processor",
            email="blank-paid-by-processor@example.com",
        )
        permission = Permission.objects.get_or_create(
            module="expenses",
            action="mark_paid",
            defaults={"name": "Mark expenses as paid"},
        )[0]
        role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Blank Paid By Processor",
            code="blank-paid-by-processor",
        )
        role.permissions.add(permission)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=processor,
            role="blank-paid-by-processor",
            organization_role=role,
        )
        processor_membership = OrganizationMembership.objects.get(user=processor, organization=self.organization)
        ProjectAssignment.objects.create(membership=processor_membership, project=self.project, role=role)
        expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("125.00"),
            description="Direct payment regression",
            status=Expense.Status.APPROVED,
        )

        response = self.client.post(
            f"/api/expenses/{expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash", "paid_by": ""},
            format="json",
            **self.auth(processor),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["paid_by"]["id"], processor.id)

    def test_mark_paid_returns_conflict_for_an_already_paid_expense(self):
        expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("125.00"),
            description="Duplicate payment regression",
            status=Expense.Status.APPROVED,
        )
        first = self.client.post(
            f"/api/expenses/{expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(self.admin),
        )
        self.assertEqual(first.status_code, 201, first.data)

        unauthorized = self.client.post(
            f"/api/expenses/{expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(unauthorized.status_code, 403)

        duplicate = self.client.post(
            f"/api/expenses/{expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(self.admin),
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(duplicate.data["code"], "expense_already_paid")
