from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import FollowUpCall, Lead, LeadAssignmentHistory, LeadStatusHistory
from organizations.models import Permission
from system_settings.models import AuditLog


class FinalSprintFixRound1ApiTests(TestCase):
    """FR-P5-02/03/05/06/08 and v2.4 regression coverage."""

    def setUp(self):
        self.organization = make_organization("final-sprint-fix-round1")
        self.project = make_project(self.organization, "FS1")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.manager.organization_role.permissions.add(Permission.objects.get(module="leads", action="edit"))
        self.telecaller.organization_role.permissions.add(Permission.objects.get(module="leads", action="edit"))
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="Round One",
            phone="9000000811",
            assigned_membership=self.telecaller,
        )
        self.client = APIClient()

    def headers(self):
        return project_request_kwargs(self.project)

    def url(self, suffix=""):
        return f"/api/v1/organizations/{self.organization.slug}/leads/{suffix}"

    def test_fr_p5_03_telecaller_patch_cannot_change_owner(self):
        self.client.force_authenticate(self.telecaller.user)
        response = self.client.patch(
            self.url(f"{self.lead.id}/"),
            {"assigned_membership": self.other_telecaller.id},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["detail"], "Use the assign action; a reason is required.")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_membership_id, self.telecaller.id)

    def test_fr_p5_08_manager_patch_cannot_change_owner(self):
        self.client.force_authenticate(self.manager.user)
        response = self.client.put(
            self.url(f"{self.lead.id}/"),
            {
                "first_name": self.lead.first_name,
                "phone": self.lead.phone,
                "source": self.lead.source,
                "assigned_membership_id": self.other_telecaller.id,
            },
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["detail"], "Use the assign action; a reason is required.")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_membership_id, self.telecaller.id)

    def test_fr_p5_03_unassign_requires_reason_and_writes_one_history_per_lead(self):
        second = make_lead(
            self.organization,
            self.project,
            first_name="Second Assigned",
            phone="9000000812",
            assigned_membership=self.other_telecaller,
        )
        self.client.force_authenticate(self.manager.user)
        missing_reason = self.client.patch(self.url("bulk_reset/"), {}, format="json", **self.headers())
        self.assertEqual(missing_reason.status_code, 400, missing_reason.data)
        self.assertEqual(LeadAssignmentHistory.objects.count(), 0)

        response = self.client.patch(
            self.url("bulk_reset/"),
            {"reason": "Owner cleared"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated_count"], 2)
        self.assertEqual(LeadAssignmentHistory.objects.count(), 2)
        self.assertEqual(
            set(LeadAssignmentHistory.objects.values_list("lead_id", flat=True)),
            {self.lead.id, second.id},
        )
        self.assertEqual(set(LeadAssignmentHistory.objects.values_list("assigned_to_id", flat=True)), {None})
        self.assertEqual(set(LeadAssignmentHistory.objects.values_list("reason", flat=True)), {"Owner cleared"})

    def test_fr_p5_05_converted_lead_blocks_source_and_score_edits(self):
        self.lead.lifecycle_status = "converted"
        self.lead.save(update_fields=["lifecycle_status", "updated_at"])
        self.client.force_authenticate(self.manager.user)
        for field, value in (("source", "google"), ("score", 99)):
            with self.subTest(field=field):
                response = self.client.patch(self.url(f"{self.lead.id}/"), {field: value}, format="json", **self.headers())
                self.assertEqual(response.status_code, 400, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.source, "website")
        self.assertEqual(self.lead.score, None)

    def test_fr_p5_06_history_rows_cannot_be_edited_or_deleted(self):
        status_history = LeadStatusHistory.objects.create(
            lead=self.lead,
            organization=self.organization,
            old_status="new",
            new_status="contacted",
        )
        assignment_history = LeadAssignmentHistory.objects.create(
            lead=self.lead,
            organization=self.organization,
            assigned_to=self.telecaller,
            reason="Initial owner",
        )
        for history, field, value in (
            (status_history, "new_status", "interested"),
            (assignment_history, "reason", "Changed"),
        ):
            with self.subTest(model=type(history).__name__, operation="save"):
                setattr(history, field, value)
                with self.assertRaises(ValidationError):
                    history.save()
            with self.subTest(model=type(history).__name__, operation="update"):
                with self.assertRaises(ValidationError):
                    type(history).objects.filter(pk=history.pk).update(**{field: value})
            with self.subTest(model=type(history).__name__, operation="delete"):
                with self.assertRaises(ValidationError):
                    history.delete()
                with self.assertRaises(ValidationError):
                    type(history).objects.filter(pk=history.pk).delete()

    def test_fr_p5_06_converted_lead_cannot_be_deleted_or_merged_as_source(self):
        self.lead.lifecycle_status = "converted"
        self.lead.save(update_fields=["lifecycle_status", "updated_at"])
        self.client.force_authenticate(self.manager.user)

        single = self.client.delete(self.url(f"{self.lead.id}/"), **self.headers())
        self.assertEqual(single.status_code, 400, single.data)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

        bulk = self.client.post(
            self.url("bulk-action/"),
            {"lead_ids": [self.lead.id], "action": "delete"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(bulk.status_code, 400, bulk.data)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

        target = make_lead(self.organization, self.project, first_name="Merge Target", phone="9000000813")
        merge = self.client.post(
            self.url("merge/"),
            {"source_lead_id": self.lead.id, "target_lead_id": target.id},
            format="json",
            **self.headers(),
        )
        self.assertEqual(merge.status_code, 400, merge.data)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_fr_p5_06_nonconverted_delete_purges_history_and_writes_old_values_audit(self):
        LeadStatusHistory.objects.create(
            lead=self.lead,
            organization=self.organization,
            old_status="new",
            new_status="contacted",
        )
        LeadAssignmentHistory.objects.create(
            lead=self.lead,
            organization=self.organization,
            assigned_to=self.telecaller,
            reason="Initial owner",
        )
        lead_id = self.lead.id
        self.client.force_authenticate(self.manager.user)
        response = self.client.delete(self.url(f"{lead_id}/"), **self.headers())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["success"])
        self.assertFalse(Lead.objects.filter(pk=lead_id).exists())
        self.assertFalse(LeadStatusHistory.objects.filter(lead_id=lead_id).exists())
        self.assertFalse(LeadAssignmentHistory.objects.filter(lead_id=lead_id).exists())
        audit = AuditLog.objects.filter(target_type="Lead", target_id=str(lead_id), action="delete").order_by("-id").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.organization_id, self.organization.id)
        self.assertEqual(audit.payload_before["first_name"], "Round One")
        self.assertEqual(audit.payload_before["assigned_membership"], self.telecaller.id)

    def test_fr_p5_02_invalid_transition_writes_no_history_or_follow_up(self):
        self.client.force_authenticate(self.manager.user)
        response = self.client.post(self.url(f"{self.lead.id}/status/"), {"status": "Converted"}, format="json", **self.headers())
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 0)
        self.assertEqual(FollowUpCall.objects.filter(lead=self.lead).count(), 0)

    def test_fr_p5_02_second_transition_is_checked_against_fresh_status(self):
        self.client.force_authenticate(self.manager.user)
        first = self.client.post(self.url(f"{self.lead.id}/status/"), {"status": "Contacted"}, format="json", **self.headers())
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(self.url(f"{self.lead.id}/status/"), {"status": "Converted"}, format="json", **self.headers())
        self.assertEqual(second.status_code, 400, second.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "contacted")
        self.assertEqual(list(LeadStatusHistory.objects.filter(lead=self.lead).values_list("old_status", "new_status")), [("new", "contacted")])
        self.assertEqual(FollowUpCall.objects.filter(lead=self.lead).count(), 1)

    def test_v24_bulk_export_requires_leads_export_permission(self):
        self.client.force_authenticate(self.manager.user)
        denied = self.client.post(
            self.url("bulk-action/"),
            {"lead_ids": [self.lead.id], "action": "export"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(denied.status_code, 403, denied.data)

        export_permission = Permission.objects.get(module="leads", action="export")
        self.manager.organization_role.permissions.add(export_permission)
        allowed = self.client.post(
            self.url("bulk-action/"),
            {"lead_ids": [self.lead.id], "action": "export"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(allowed.data["count"], 1)
