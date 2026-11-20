from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.tasks import task
from django.utils import timezone


@task
def task5_success(value, label=None):
    return {"value": value, "label": label}


@task
def task5_failure():
    raise ValueError("customer secret must never be persisted")


class DatabaseTaskTests(TestCase):
    """G-3 item 3 / NFR-P4-01 Django Tasks database backend."""

    def test_default_backend_is_the_core_database_backend_g_3_item_3(self):
        self.assertEqual(
            settings.TASKS["default"]["BACKEND"],
            "core.tasks_backend.DatabaseTaskBackend",
        )

    def test_worker_start_line_reports_database_and_environment_without_secrets_g_3_item_3(self):
        output = StringIO()

        call_command("run_worker", "--once", stdout=output)

        line = output.getvalue().strip()
        self.assertIn(
            f"Worker started: database {settings.DATABASES['default']['NAME']}, "
            f"environment {settings.ENVIRONMENT_NAME}",
            line,
        )
        self.assertNotIn("FILE_ENCRYPTION_KEY", line)
        self.assertNotIn("DJANGO_SECRET_KEY", line)

    def test_enqueue_creates_one_queued_record_with_json_arguments_g_3_item_3(self):
        from core.models import TaskRecord

        result = task5_success.enqueue(7, label="import")
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(TaskRecord.objects.count(), 1)
        self.assertEqual(record.status, TaskRecord.Status.READY)
        self.assertEqual(record.task_path, task5_success.module_path)
        self.assertEqual(record.args, [7])
        self.assertEqual(record.kwargs, {"label": "import"})
        self.assertIsNotNone(record.run_after)
        self.assertEqual(record.attempts, 0)

    def test_worker_once_succeeds_and_stores_return_value_g_3_item_3(self):
        from core.models import TaskRecord

        result = task5_success.enqueue(9, label="worker")
        call_command("run_worker", "--once")
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(record.status, TaskRecord.Status.SUCCESSFUL)
        self.assertEqual(record.return_value, {"value": 9, "label": "worker"})
        self.assertEqual(record.attempts, 1)

    def test_failed_task_stores_exception_type_without_message_g_3_item_3(self):
        from core.models import TaskRecord

        result = task5_failure.enqueue()
        with self.settings(TASK_RETRY_DELAY_SECONDS=0):
            for _ in range(settings.TASK_MAX_ATTEMPTS):
                call_command("run_worker", "--once")
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(record.status, TaskRecord.Status.FAILED)
        self.assertEqual(record.error_type, "builtins.ValueError")
        self.assertNotIn("customer secret", str(record.__dict__))

    def test_failed_task_retries_up_to_default_maximum_nfr_p4_01(self):
        from core.models import TaskRecord

        result = task5_failure.enqueue()
        with self.settings(TASK_RETRY_DELAY_SECONDS=0):
            call_command("run_worker", "--once")
            record = TaskRecord.objects.get(pk=result.id)
            self.assertEqual(record.status, TaskRecord.Status.READY)
            self.assertEqual(record.attempts, 1)

    def test_two_claims_cannot_run_the_same_task_gnfr_11(self):
        from core.tasks_backend import get_database_backend

        task5_success.enqueue(1)
        backend = get_database_backend()
        first = backend.claim_due_task("worker-one")
        second = backend.claim_due_task("worker-two")

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_future_task_is_not_run_until_run_after_g_3_item_3(self):
        from core.models import TaskRecord

        future = task5_success.using(run_after=timezone.now() + timedelta(hours=1))
        result = future.enqueue(3)
        call_command("run_worker", "--once")

        record = TaskRecord.objects.get(pk=result.id)
        self.assertEqual(record.status, TaskRecord.Status.READY)
        self.assertEqual(record.attempts, 0)

    def test_stale_running_task_is_recovered_and_runs_g_3_item_3_fr_p8_04(self):
        from core.models import TaskRecord
        from core.tasks_backend import get_database_backend

        result = task5_success.enqueue(12)
        TaskRecord.objects.filter(pk=result.id).update(
            status=TaskRecord.Status.RUNNING,
            started_at=timezone.now() - timedelta(
                seconds=settings.TASK_RUNNING_TIMEOUT_SECONDS + 1
            ),
            attempts=1,
            worker_ids=["dead-worker"],
        )

        self.assertTrue(get_database_backend().run_once("replacement-worker"))
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(record.status, TaskRecord.Status.SUCCESSFUL)
        self.assertEqual(record.attempts, 2)
        self.assertEqual(record.worker_ids, ["dead-worker", "replacement-worker"])

    def test_stale_running_task_at_max_attempts_fails_worker_lost_g_3_item_3_fr_p9_06(self):
        from core.models import TaskRecord
        from core.tasks_backend import get_database_backend

        result = task5_success.enqueue(13)
        TaskRecord.objects.filter(pk=result.id).update(
            status=TaskRecord.Status.RUNNING,
            started_at=timezone.now() - timedelta(
                seconds=settings.TASK_RUNNING_TIMEOUT_SECONDS + 1
            ),
            attempts=settings.TASK_MAX_ATTEMPTS,
            worker_ids=["dead-worker"],
        )

        self.assertFalse(get_database_backend().run_once("replacement-worker"))
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(record.status, TaskRecord.Status.FAILED)
        self.assertEqual(record.error_type, "worker_lost")
        self.assertEqual(record.attempts, settings.TASK_MAX_ATTEMPTS)

    def test_recent_running_task_is_not_recovered_g_3_item_3_gnfr_11(self):
        from core.models import TaskRecord
        from core.tasks_backend import get_database_backend

        result = task5_success.enqueue(14)
        started_at = timezone.now() - timedelta(
            seconds=settings.TASK_RUNNING_TIMEOUT_SECONDS - 1
        )
        TaskRecord.objects.filter(pk=result.id).update(
            status=TaskRecord.Status.RUNNING,
            started_at=started_at,
            attempts=1,
            worker_ids=["active-worker"],
        )

        self.assertIsNone(get_database_backend().claim_due_task("replacement-worker"))
        record = TaskRecord.objects.get(pk=result.id)

        self.assertEqual(record.status, TaskRecord.Status.RUNNING)
        self.assertEqual(record.started_at, started_at)
        self.assertEqual(record.attempts, 1)
        self.assertEqual(record.worker_ids, ["active-worker"])

    def test_stale_recovery_and_claim_are_atomic_gnfr_11(self):
        from core.models import TaskRecord
        from core.tasks_backend import get_database_backend

        result = task5_success.enqueue(15)
        TaskRecord.objects.filter(pk=result.id).update(
            status=TaskRecord.Status.RUNNING,
            started_at=timezone.now() - timedelta(
                seconds=settings.TASK_RUNNING_TIMEOUT_SECONDS + 1
            ),
            attempts=1,
            worker_ids=["dead-worker"],
        )
        backend = get_database_backend()

        first = backend.claim_due_task("replacement-worker")
        second = backend.claim_due_task("second-worker")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        record = TaskRecord.objects.get(pk=result.id)
        self.assertEqual(record.status, TaskRecord.Status.RUNNING)
        self.assertEqual(record.attempts, 2)
        self.assertEqual(record.worker_ids, ["dead-worker", "replacement-worker"])


class PostgreSQLTaskClaimTests(TransactionTestCase):
    """GNFR-11 / G-3 item 8 PostgreSQL worker locking."""

    @skipUnlessDBFeature(
        "has_select_for_update",
        "Requires PostgreSQL TEST_DATABASE_URL; skipped on SQLite.",
    )
    def test_postgresql_worker_claim_uses_the_database_lock_path_gnfr_11(self):
        from core.models import TaskRecord
        from core.tasks_backend import get_database_backend

        result = task5_success.enqueue(11)
        claimed = get_database_backend().claim_due_task("postgres-worker")

        self.assertEqual(claimed.pk, result.id)
        self.assertEqual(
            TaskRecord.objects.get(pk=result.id).status,
            TaskRecord.Status.RUNNING,
        )

