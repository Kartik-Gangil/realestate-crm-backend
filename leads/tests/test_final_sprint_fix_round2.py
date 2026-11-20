from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import importlib
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.apps import apps
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Notification
from core.tasks_backend import get_database_backend, process_due_reminders
from core.tests.factories import make_lead, make_member, make_organization, make_project, project_request_kwargs
from leads.models import FollowUpCall, LeadStatusHistory, Sitevisit
from system_settings.models import SystemParameter
from system_settings.parameters import PARAMETER_REGISTRY


class FinalSprintFixRound2ApiTests(TestCase):
    """FR-P5-02, FR-P6-08, FR-P7-01 and FR-P7-06 regression coverage."""

    def setUp(self):
        self.organization = make_organization("final-sprint-fix-round2")
        self.project = make_project(self.organization, "FS2")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="Round Two",
            phone="9000000821",
            assigned_membership=self.telecaller,
            score=40,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager.user)
        self.set_parameter("site_visit_max_days_ahead", 90)
        self.set_parameter("site_visit_reminder_days", 1)

    def set_parameter(self, key, value):
        definition = PARAMETER_REGISTRY.get(key)
        SystemParameter.objects.update_or_create(
            organization=self.organization,
            project=self.project,
            parameter_key=key,
            defaults={
                "parameter_name": definition.name if definition else key.replace("_", " ").title(),
                "value": value,
                "data_type": definition.data_type if definition else SystemParameter.DataType.INTEGER,
                "is_active": True,
            },
        )
        cache.clear()

    def headers(self):
        return project_request_kwargs(self.project)

    def site_visit_url(self):
        return reverse("leads:site-visit", args=[self.organization.slug])

    def telecalling_analytics_url(self):
        return f"/api/v1/organizations/{self.organization.slug}/telecalling/analytics/"

    def schedule(self, *, lead=None, executive=None, days=1, time="10:00:00"):
        return self.client.post(
            self.site_visit_url(),
            {
                "lead": lead or self.lead.id,
                "executive": executive or self.executive.id,
                "visit_date": (timezone.localdate() + timedelta(days=days)).isoformat(),
                "visit_time": time,
                "duration_minutes": 60,
                "site": "Round Two Site",
            },
            format="json",
            **self.headers(),
        )

    def complete(self, visit):
        Sitevisit.objects.filter(pk=visit.pk).update(status=Sitevisit.Status.IN_PROGRESS)
        return self.client.post(
            reverse("leads:site-visit-outcome", args=[self.organization.slug, visit.pk]),
            {"outcome": "interested", "interest_level": 5},
            format="json",
            **self.headers(),
        )

    def test_fr_p5_02_second_visits_do_not_move_status_backward_or_write_history(self):
        first_response = self.schedule(days=1, time="10:00:00")
        self.assertEqual(first_response.status_code, 201, first_response.data)
        first_visit = Sitevisit.objects.get(pk=first_response.data["id"])
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 1)

        completed_first = self.complete(first_visit)
        self.assertEqual(completed_first.status_code, 200, completed_first.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "site_visit_completed")
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 2)

        second_response = self.schedule(days=2, time="12:00:00")
        self.assertEqual(second_response.status_code, 201, second_response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "site_visit_completed")
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 2)

        second_visit = Sitevisit.objects.get(pk=second_response.data["id"])
        completed_second = self.complete(second_visit)
        self.assertEqual(completed_second.status_code, 200, completed_second.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.score, 80)
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), 2)

    def test_fr_p5_02_lost_lead_completion_keeps_lost_status_and_adds_score(self):
        scheduled = self.schedule(days=1)
        self.assertEqual(scheduled.status_code, 201, scheduled.data)
        visit = Sitevisit.objects.get(pk=scheduled.data["id"])
        history_before = LeadStatusHistory.objects.filter(lead=self.lead).count()
        lost = self.client.post(
            reverse("leads:transition-status", args=[self.organization.slug, self.lead.id]),
            {"status": "lost", "reason": "Customer withdrew"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(lost.status_code, 201, lost.data)
        Sitevisit.objects.filter(pk=visit.pk).update(status=Sitevisit.Status.IN_PROGRESS)

        completed = self.complete(visit)

        self.assertEqual(completed.status_code, 200, completed.data)
        self.lead.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(self.lead.lifecycle_status, "lost")
        self.assertEqual(self.lead.score, 60)
        self.assertEqual(visit.outcome, "interested")
        self.assertEqual(LeadStatusHistory.objects.filter(lead=self.lead).count(), history_before + 1)

    def test_fr_p6_08_system_site_visit_transitions_do_not_create_calls_or_change_analytics(self):
        analytics_client = APIClient()
        analytics_client.force_authenticate(self.telecaller.user)
        before = analytics_client.get(
            self.telecalling_analytics_url(),
            **self.headers(),
        )
        self.assertEqual(before.status_code, 200, before.data)

        scheduled = self.schedule(days=1)
        self.assertEqual(scheduled.status_code, 201, scheduled.data)
        visit = Sitevisit.objects.get(pk=scheduled.data["id"])
        self.assertEqual(FollowUpCall.objects.filter(lead=self.lead).count(), 0)
        completed = self.complete(visit)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(FollowUpCall.objects.filter(lead=self.lead).count(), 0)

        after = analytics_client.get(
            self.telecalling_analytics_url(),
            **self.headers(),
        )
        self.assertEqual(after.status_code, 200, after.data)
        for key in ("calls_today", "connected", "follow_ups_due"):
            self.assertEqual(after.data[key], before.data[key], key)

    def test_fr_p7_06_parameter_limit_applies_to_schedule_and_reschedule(self):
        self.set_parameter("site_visit_max_days_ahead", 30)
        too_far = self.schedule(days=31)
        self.assertEqual(too_far.status_code, 400, too_far.data)

        allowed = self.schedule(days=30, time="11:00:00")
        self.assertEqual(allowed.status_code, 201, allowed.data)
        visit = Sitevisit.objects.get(pk=allowed.data["id"])
        reschedule_url = reverse("leads:site-visit-reschedule", args=[self.organization.slug, visit.id])
        too_far_reschedule = self.client.post(
            reschedule_url,
            {"new_date": (timezone.localdate() + timedelta(days=31)).isoformat(), "new_time": "12:00:00", "reason": "Move later"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(too_far_reschedule.status_code, 400, too_far_reschedule.data)
        allowed_reschedule = self.client.post(
            reschedule_url,
            {"new_date": (timezone.localdate() + timedelta(days=30)).isoformat(), "new_time": "12:00:00", "reason": "Customer request"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(allowed_reschedule.status_code, 201, allowed_reschedule.data)

    def test_fr_p7_01_reschedule_rejects_an_executive_clash(self):
        first = self.schedule(lead=self.lead.id, time="10:00:00")
        self.assertEqual(first.status_code, 201, first.data)
        second_lead = make_lead(self.organization, self.project, first_name="Second", phone="9000000822")
        second = self.schedule(lead=second_lead.id, executive=self.executive.id, time="12:00:00")
        self.assertEqual(second.status_code, 201, second.data)
        reschedule_url = reverse("leads:site-visit-reschedule", args=[self.organization.slug, second.data["id"]])
        response = self.client.post(
            reschedule_url,
            {"new_date": (timezone.localdate() + timedelta(days=1)).isoformat(), "new_time": "10:00:00", "reason": "Executive change"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.data)


class FinalSprintFixRound2ReminderTests(TestCase):
    """FR-P6-06/FR-P7-08 worker reminder coverage."""

    def setUp(self):
        self.organization = make_organization("final-sprint-reminders")
        self.other_organization = make_organization("final-sprint-reminders-other")
        self.project = make_project(self.organization, "REM")
        self.other_project = make_project(self.other_organization, "REM-OTHER")
        self.telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        self.executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_executive = make_member(self.other_organization, role="telecaller", projects=[self.other_project])
        self.lead = make_lead(self.organization, self.project, phone="9000000831", assigned_membership=self.telecaller)
        self.other_lead = make_lead(self.other_organization, self.other_project, phone="9000000832", assigned_membership=self.other_executive)
        for organization, project in ((self.organization, self.project), (self.other_organization, self.other_project)):
            for key, value in (("site_visit_reminder_days", 1),):
                SystemParameter.objects.update_or_create(
                    organization=organization,
                    project=project,
                    parameter_key=key,
                    defaults={"parameter_name": "Site visit reminder days", "value": value, "data_type": SystemParameter.DataType.INTEGER, "is_active": True},
                )
        cache.clear()

    def run_worker_once(self):
        import core.tasks_backend as tasks_backend
        tasks_backend._last_reminder_run_at = None
        call_command("run_worker", "--once")

    def test_fr_p6_06_due_follow_up_notifies_once_and_not_before_due_time(self):
        not_due = FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.lead,
            telecaller_membership=self.telecaller,
            next_follow_up=timezone.now() + timedelta(days=1),
        )
        self.run_worker_once()
        self.assertEqual(Notification.objects.filter(type="telecalling.follow_up_due").count(), 0)

        not_due.next_follow_up = timezone.now() - timedelta(minutes=1)
        not_due.save(update_fields=["next_follow_up"])
        self.run_worker_once()
        reminder = Notification.objects.get(type="telecalling.follow_up_due")
        self.assertEqual(reminder.recipient_membership_id, self.telecaller.id)
        not_due.refresh_from_db()
        self.assertTrue(not_due.reminder_sent)

        self.run_worker_once()
        self.assertEqual(Notification.objects.filter(type="telecalling.follow_up_due").count(), 1)

    def test_fr_p7_08_site_visit_reminders_are_due_once_scoped_and_skip_terminal_visits(self):
        due = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )
        future = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate() + timedelta(days=2),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )
        for terminal_status, offset in ((Sitevisit.Status.CANCELLED, 1), (Sitevisit.Status.NO_SHOW, 1), (Sitevisit.Status.COMPLETED, 1)):
            Sitevisit.objects.create(
                organization=self.organization,
                project=self.project,
                lead=self.lead,
                executive_membership=self.executive,
                visit_date=timezone.localdate() - timedelta(days=offset),
                visit_time="10:00",
                status=terminal_status,
            )
        other_due = Sitevisit.objects.create(
            organization=self.other_organization,
            project=self.other_project,
            lead=self.other_lead,
            executive_membership=self.other_executive,
            visit_date=timezone.localdate(),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )

        self.run_worker_once()
        reminders = Notification.objects.filter(type="site_visit.reminder")
        self.assertEqual(reminders.count(), 2)
        self.assertEqual(set(reminders.values_list("recipient_membership_id", flat=True)), {self.executive.id, self.other_executive.id})
        due.refresh_from_db()
        future.refresh_from_db()
        other_due.refresh_from_db()
        self.assertIsNotNone(due.reminder_sent_at)
        self.assertIsNone(future.reminder_sent_at)
        self.assertIsNotNone(other_due.reminder_sent_at)
        self.assertEqual(
            Sitevisit.objects.filter(
                reminder_sent_at__isnull=False,
                status__in=[Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW, Sitevisit.Status.COMPLETED],
            ).count(),
            0,
        )

        self.run_worker_once()
        self.assertEqual(Notification.objects.filter(type="site_visit.reminder").count(), 2)

    def test_fr_p7_08_old_visits_are_not_reminded_but_tomorrow_is_due(self):
        old_visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate() - timedelta(days=1),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )
        tomorrow = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            executive_membership=self.executive,
            visit_date=timezone.localdate() + timedelta(days=1),
            visit_time="10:00",
            status=Sitevisit.Status.UPCOMING,
        )

        self.run_worker_once()

        self.assertEqual(Notification.objects.filter(type="site_visit.reminder").count(), 1)
        old_visit.refresh_from_db()
        tomorrow.refresh_from_db()
        self.assertIsNone(old_visit.reminder_sent_at)
        self.assertIsNotNone(tomorrow.reminder_sent_at)

    def test_fr_p6_06_converted_lost_and_inactive_followups_are_marked_sent_without_notifications(self):
        converted_lead = make_lead(
            self.organization, self.project, phone="9000000833", lifecycle_status="converted"
        )
        lost_lead = make_lead(
            self.organization, self.project, phone="9000000834", lifecycle_status="lost"
        )
        inactive = make_member(self.organization, role="telecaller", projects=[self.project])
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        inactive_lead = make_lead(
            self.organization, self.project, phone="9000000835", assigned_membership=inactive
        )
        due = timezone.now() - timedelta(minutes=1)
        rows = [
            FollowUpCall.objects.create(
                organization=self.organization, lead=converted_lead,
                telecaller_membership=self.telecaller, next_follow_up=due,
            ),
            FollowUpCall.objects.create(
                organization=self.organization, lead=lost_lead,
                telecaller_membership=self.telecaller, next_follow_up=due,
            ),
            FollowUpCall.objects.create(
                organization=self.organization, lead=inactive_lead,
                telecaller_membership=inactive, next_follow_up=due,
            ),
        ]

        self.run_worker_once()

        self.assertEqual(Notification.objects.filter(type="telecalling.follow_up_due").count(), 0)
        self.assertEqual(set(FollowUpCall.objects.filter(pk__in=[row.pk for row in rows], reminder_sent=True).values_list("pk", flat=True)), {row.pk for row in rows})

    def test_fr_p6_06_one_failed_reminder_row_does_not_stop_the_other(self):
        first_lead = make_lead(self.organization, self.project, phone="9000000836")
        second_lead = make_lead(self.organization, self.project, phone="9000000837")
        due = timezone.now() - timedelta(minutes=1)
        first = FollowUpCall.objects.create(
            organization=self.organization, lead=first_lead,
            telecaller_membership=self.telecaller, next_follow_up=due,
        )
        second = FollowUpCall.objects.create(
            organization=self.organization, lead=second_lead,
            telecaller_membership=self.telecaller, next_follow_up=due,
        )
        original_create = Notification.objects.create

        def create_notification(**kwargs):
            if kwargs.get("related_object_id") == first.lead_id:
                raise RuntimeError("simulated reminder failure")
            return original_create(**kwargs)

        with self.assertLogs("core.tasks_backend", level="ERROR") as captured:
            with patch.object(Notification.objects, "create", side_effect=create_notification):
                process_due_reminders()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.reminder_sent)
        self.assertTrue(second.reminder_sent)
        self.assertEqual(Notification.objects.filter(type="telecalling.follow_up_due").count(), 1)
        log_text = "\n".join(captured.output)
        self.assertIn(f"row id={first.pk}", log_text)
        self.assertNotIn(first_lead.full_name, log_text)
        self.assertNotIn(first_lead.phone, log_text)

    def test_fr_p6_06_run_once_continues_to_queued_task_after_reminder_failure(self):
        from core.tests.test_tasks import task5_success

        result = task5_success.enqueue("round3")
        with patch("core.tasks_backend.process_due_reminders", side_effect=RuntimeError("worker reminder failure")):
            self.assertTrue(get_database_backend().run_once("round3-worker"))
        record = get_database_backend().get_result(result.id)
        self.assertEqual(record.status.value, "SUCCESSFUL")

    def test_fr_p6_06_run_once_throttles_reminder_scan_but_once_mode_runs_it(self):
        import core.tasks_backend as tasks_backend

        tasks_backend._last_reminder_run_at = None
        with self.settings(REMINDER_INTERVAL_SECONDS=60), patch("core.tasks_backend.process_due_reminders") as process:
            self.assertFalse(get_database_backend().run_once("round3-worker-one"))
            self.assertFalse(get_database_backend().run_once("round3-worker-two"))
            self.assertEqual(process.call_count, 1)

        tasks_backend._last_reminder_run_at = None
        with patch("core.tasks_backend.process_due_reminders") as process:
            call_command("run_worker", "--once")
            process.assert_called_once_with()


class FinalSprintFixRound3MigrationTests(TestCase):
    """FR-P6-06/FR-P7-08 migration backfill coverage."""

    def test_fr_p6_06_0034_marks_reminders_before_migration_time_as_sent(self):
        organization = make_organization("final-sprint-round3-migration")
        project = make_project(organization, "MIG3")
        telecaller = make_member(organization, role="telecaller", projects=[project])
        lead = make_lead(organization, project, phone="9000000838", assigned_membership=telecaller)
        old_call = FollowUpCall.objects.create(
            organization=organization, lead=lead, telecaller_membership=telecaller,
            next_follow_up=timezone.now() - timedelta(minutes=1),
        )
        future_call = FollowUpCall.objects.create(
            organization=organization, lead=lead, telecaller_membership=telecaller,
            next_follow_up=timezone.now() + timedelta(days=1),
        )
        old_visit = Sitevisit.objects.create(
            organization=organization, project=project, lead=lead,
            executive_membership=telecaller, visit_date=timezone.localdate() - timedelta(days=1),
            visit_time="10:00", status=Sitevisit.Status.UPCOMING,
        )
        future_visit = Sitevisit.objects.create(
            organization=organization, project=project, lead=lead,
            executive_membership=telecaller, visit_date=timezone.localdate() + timedelta(days=1),
            visit_time="10:00", status=Sitevisit.Status.UPCOMING,
        )

        migration = importlib.import_module("leads.migrations.0034_mark_old_reminders_sent")
        migration.mark_old_reminders_sent(apps, None)

        old_call.refresh_from_db()
        future_call.refresh_from_db()
        old_visit.refresh_from_db()
        future_visit.refresh_from_db()
        self.assertTrue(old_call.reminder_sent)
        self.assertFalse(future_call.reminder_sent)
        self.assertIsNotNone(old_visit.reminder_sent_at)
        self.assertIsNone(future_visit.reminder_sent_at)


class FinalSprintFixRound2ConcurrencyTests(TransactionTestCase):
    """FR-P7-01/GNFR-11 parallel executive-clash coverage."""

    reset_sequences = True

    def setUp(self):
        self.organization = make_organization("final-sprint-clash-lock")
        self.project = make_project(self.organization, "CLASH")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.executive = make_member(self.organization, role="telecaller", projects=[self.project])
        self.first_lead = make_lead(
            self.organization, self.project, phone="9000000841", assigned_membership=self.manager
        )
        self.second_lead = make_lead(
            self.organization, self.project, phone="9000000842", assigned_membership=self.manager
        )

    def book(self, lead_id):
        close_old_connections()
        try:
            client = APIClient()
            client.raise_request_exception = False
            client.force_authenticate(self.manager.user)
            return client.post(
                reverse("leads:site-visit", args=[self.organization.slug]),
                {
                    "lead": lead_id,
                    "executive": self.executive.id,
                    "visit_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                    "visit_time": "10:00:00",
                    "duration_minutes": 60,
                    "site": "Clash Site",
                },
                format="json",
                **project_request_kwargs(self.project),
            )
        finally:
            close_old_connections()

    def test_fr_p7_01_parallel_overlapping_bookings_have_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(self.book, [self.first_lead.id, self.second_lead.id]))
        statuses = sorted(response.status_code for response in responses)
        self.assertEqual(statuses.count(201), 1, statuses)
        loser_statuses = [code for code in statuses if code != 201]
        self.assertEqual(len(loser_statuses), 1, statuses)
        self.assertIn(loser_statuses[0], {400, 503}, statuses)
