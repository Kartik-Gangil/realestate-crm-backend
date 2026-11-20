"""Task 11 fix round 6 regression tests.

Task/Phase IDs: FR-P3-04, UI-P3-04, FR-P3-02, FR-P16-02, FR-P16-03,
EC-P3-01, GNFR-05, and G-1 item 10.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from expenses.models import Expense, ExpenseCategory
from organizations.models import OrganizationRole, Permission
from system_settings.models import AuditLog
from users.models import DeveloperAccount


class Task11OrganizationAuditTests(TestCase):
    """FR-P3-04/API-P3-07: Developer organization audit access is project-free."""

    def test_role_permission_change_is_returned_without_project_header(self):
        organization = make_organization("round6-audit-org")
        developer = get_user_model().objects.create_user(
            username="round6-developer@example.test",
            email="round6-developer@example.test",
            password="Valid123!",
        )
        DeveloperAccount.objects.create(user=developer)
        role = OrganizationRole.objects.create(
            organization=organization,
            name="Round 6 custom role",
            code="round6-custom-role",
        )
        old_permission = Permission.objects.get_or_create(
            module="leads", action="view", defaults={"name": "View leads", "scope": "project"}
        )[0]
        new_permission = Permission.objects.get_or_create(
            module="leads", action="export", defaults={"name": "Export leads", "scope": "project"}
        )[0]
        role.permissions.add(old_permission)
        client = APIClient()
        client.force_authenticate(developer)

        changed = client.put(
            f"/api/v1/organizations/{organization.slug}/roles/{role.pk}/permissions/",
            {"permission_ids": [new_permission.pk]},
            format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.data)

        response = client.get(f"/api/v1/organizations/{organization.slug}/audit-logs/")
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data.get("data", response.data)
        rows = payload["results"]
        row = next(item for item in rows if item["action"] == "permissions")
        self.assertEqual(row["project"], None)
        self.assertEqual(row["details"]["added"], ["leads.export"])
        self.assertEqual(row["details"]["removed"], ["leads.view"])


class Task11ExpensePermissionTests(TestCase):
    """FR-P16-02/DM-P3-02(v2.4): edit is not approval or receipt-download access."""

    def test_edit_without_approve_or_export_cannot_approve_or_read_pending_receipt(self):
        organization = make_organization("round6-expense-org")
        project = make_project(organization, "ROUND6")
        membership = make_member(organization, role="telecaller", projects=[project])
        role = membership.organization_role
        role.permissions.set([
            Permission.objects.get_or_create(
                module="expenses", action=action, defaults={"name": f"expenses.{action}"}
            )[0]
            for action in ("view", "edit")
        ])
        category = ExpenseCategory.objects.create(
            organization=organization, project=project, name="Round 6 travel"
        )
        expense = Expense.objects.create(
            organization=organization,
            project=project,
            submitted_by=membership.user,
            category=category,
            amount=Decimal("125.00"),
            description="Pending expense",
            status=Expense.Status.PENDING_APPROVAL,
            # The authorization check must run before storage access; a name is
            # enough to exercise the protected receipt endpoint.
            receipt="expenses/round6/receipt.pdf",
        )
        client = APIClient()
        client.force_authenticate(membership.user)
        headers = {"HTTP_X_PROJECT_ID": str(project.pk)}

        approve = client.post(f"/api/expenses/{expense.pk}/approve/", {}, format="json", **headers)
        receipt = client.get(f"/api/expenses/{expense.pk}/receipt/", **headers)

        self.assertEqual(approve.status_code, 403, approve.data)
        self.assertEqual(receipt.status_code, 403, receipt.data)


class Task11NormalUserCreationTests(TestCase):
    """G-1 item 10: API employee creation cannot create privileged accounts."""

    def test_privileged_fields_in_users_post_still_create_a_normal_user(self):
        organization = make_organization("round6-users-org")
        admin = make_member(organization, role="admin")
        client = APIClient()
        client.force_authenticate(admin.user)

        response = client.post(
            f"/api/v1/organizations/{organization.slug}/users/",
            {
                "email": "round6-normal@example.test",
                "temporary_password": "Valid123!",
                "first_name": "Normal",
                "last_name": "User",
                "role": "telecaller",
                "is_superuser": True,
                "is_staff": True,
                "groups": ["Platform Admin"],
                "is_developer": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        user = get_user_model().objects.get(email="round6-normal@example.test")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name="Platform Admin").exists())
        self.assertFalse(DeveloperAccount.objects.filter(user=user).exists())
        self.assertFalse(AuditLog.objects.filter(target_type="DeveloperAccount", target_id=str(user.pk)).exists())
