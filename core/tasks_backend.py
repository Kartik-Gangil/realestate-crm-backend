import importlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.tasks.base import TaskContext, TaskError, TaskResult, TaskResultStatus
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.exceptions import TaskResultDoesNotExist
from django.tasks.signals import task_enqueued, task_finished, task_started
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.json import normalize_json

from .models import TaskRecord


logger = logging.getLogger(__name__)
_last_reminder_run_at = None


def process_due_reminders():
    """Process due reminders and expiry rows once, row by row."""
    from leads.models import FollowUpCall, Sitevisit
    from system_settings.parameters import PARAMETER_REGISTRY
    from system_settings.services import UnknownSystemParameter, get_system_parameter

    now = timezone.now()
    today = timezone.localdate()
    created = 0
    follow_up_ids = list(FollowUpCall.objects.filter(
        next_follow_up__isnull=False,
        next_follow_up__lte=now,
        reminder_sent=False,
        telecaller_membership__isnull=False,
    ).values_list("pk", flat=True))
    visit_ids = list(Sitevisit.objects.filter(
        visit_date__isnull=False,
        visit_date__gte=today,
        executive_membership__isnull=False,
        reminder_sent_at__isnull=True,
    ).exclude(
        status__in=[Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW, Sitevisit.Status.COMPLETED]
    ).values_list("pk", flat=True))

    from .models import Notification

    for row_id in follow_up_ids:
        try:
            with transaction.atomic():
                follow_up = FollowUpCall.objects.select_for_update().select_related(
                    "organization", "lead__project", "telecaller_membership"
                ).filter(pk=row_id).first()
                if follow_up is None or follow_up.reminder_sent:
                    continue
                if follow_up.lead.lifecycle_status in {"converted", "lost"} or not follow_up.telecaller_membership.is_active:
                    follow_up.reminder_sent = True
                    follow_up.save(update_fields=["reminder_sent"])
                    continue
                Notification.objects.create(
                    organization=follow_up.organization,
                    project=follow_up.lead.project,
                    recipient_membership=follow_up.telecaller_membership,
                    type="telecalling.follow_up_due",
                    title="Follow-up due",
                    body=f"Follow up with {follow_up.lead.full_name} is due.",
                    related_object_type="Lead",
                    related_object_id=follow_up.lead_id,
                )
                follow_up.reminder_sent = True
                follow_up.save(update_fields=["reminder_sent"])
                created += 1
        except Exception:
            logger.exception("Reminder processing failed for row id=%s", row_id)

    for row_id in visit_ids:
        try:
            with transaction.atomic():
                visit = Sitevisit.objects.select_for_update().select_related(
                    "organization", "project", "lead", "executive_membership"
                ).filter(pk=row_id).first()
                if (
                    visit is None
                    or visit.reminder_sent_at is not None
                    or visit.visit_date is None
                    or visit.visit_date < today
                    or visit.status in {Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW, Sitevisit.Status.COMPLETED}
                ):
                    continue
                try:
                    reminder_days = int(get_system_parameter(
                        visit.organization, "site_visit_reminder_days", project=visit.project
                    ))
                except UnknownSystemParameter:
                    reminder_days = int(PARAMETER_REGISTRY["site_visit_reminder_days"].default)
                if today < visit.visit_date - timedelta(days=reminder_days):
                    continue
                Notification.objects.create(
                    organization=visit.organization,
                    project=visit.project,
                    recipient_membership=visit.executive_membership,
                    type="site_visit.reminder",
                    title="Site visit reminder",
                    body=f"Site visit for {visit.lead.full_name} is due on {visit.visit_date}.",
                    related_object_type="Sitevisit",
                    related_object_id=visit.pk,
                )
                visit.reminder_sent_at = now
                visit.save(update_fields=["reminder_sent_at", "updated_at"])
                created += 1
        except Exception:
            logger.exception("Reminder processing failed for row id=%s", row_id)
    created += process_due_plot_holds()
    created += process_due_bookings()
    return created


def process_due_plot_holds():
    """Return expired temporary plot holds/blocks to Available, isolating failures per row."""
    from inventory.models import Plot, PlotHold
    from inventory.services import _change_locked_plot_status

    now = timezone.now()
    hold_ids = list(
        PlotHold.objects.filter(released_at__isnull=True)
        .filter(Q(expires_at__isnull=False, expires_at__lte=now) | Q(expires_at__isnull=True, to_datetime__lte=now))
        .values_list("pk", flat=True)
    )
    processed = 0
    for hold_id in hold_ids:
        try:
            with transaction.atomic():
                hold = PlotHold.objects.select_for_update().select_related("plot").filter(pk=hold_id, released_at__isnull=True).first()
                if hold is None:
                    continue
                plot = Plot.objects.select_for_update().get(pk=hold.plot_id)
                if plot.status == (Plot.Status.HOLD if hold.action_type == PlotHold.ActionType.HOLD else Plot.Status.BLOCKED):
                    _change_locked_plot_status(plot, Plot.Status.AVAILABLE, "Temporary plot hold/block expired", None)
                hold.released_at = now
                hold.save(update_fields=["released_at"])
                processed += 1
        except Exception:
            logger.exception("Plot hold expiry failed for row id=%s", hold_id)
    return processed


def process_due_bookings():
    """Expire booking holds and release their plots after the configured windows."""
    from inventory.models import Plot, PlotBooking
    from inventory.phase5_services import payment_totals
    from inventory.services import change_plot_status
    from system_settings.parameters import PARAMETER_REGISTRY
    from system_settings.services import UnknownSystemParameter, get_system_parameter

    now = timezone.now()
    candidates = list(PlotBooking.objects.filter(
        status__in=[PlotBooking.Status.CREATED, PlotBooking.Status.PENDING, PlotBooking.Status.PARTIALLY_PAID],
        hold_expires_at__isnull=False,
        hold_expires_at__lte=now,
    ).values_list("pk", flat=True))
    processed = 0
    for booking_id in candidates:
        try:
            with transaction.atomic():
                booking = PlotBooking.objects.select_for_update().select_related("organization", "project").filter(pk=booking_id).first()
                if booking is None or booking.status not in {PlotBooking.Status.CREATED, PlotBooking.Status.PENDING, PlotBooking.Status.PARTIALLY_PAID}:
                    continue
                if not booking.hold_expires_at or booking.hold_expires_at > now:
                    continue
                try:
                    minimum_percent = Decimal(str(get_system_parameter(
                        booking.organization,
                        "booking_minimum_payment_percent",
                        project=booking.project,
                    )))
                except UnknownSystemParameter:
                    minimum_percent = Decimal(str(PARAMETER_REGISTRY["booking_minimum_payment_percent"].default))
                total = booking.total_amount or booking.final_price or Decimal("0")
                minimum_amount = (total * minimum_percent / Decimal("100")).quantize(Decimal("0.01"))
                paid = payment_totals(booking)["net_paid"]
                if paid > 0 and paid >= minimum_amount:
                    if booking.hold_expires_at is not None:
                        booking.hold_expires_at = None
                        booking.save(update_fields=["hold_expires_at", "updated_at"])
                    continue
                plot = Plot.objects.select_for_update().get(pk=booking.plot_id)
                if plot.status == Plot.Status.HOLD:
                    change_plot_status(plot=plot, new_status=Plot.Status.AVAILABLE, reason="Booking expired", user=None)
                elif plot.status == Plot.Status.BOOKED:
                    change_plot_status(plot=plot, new_status=Plot.Status.CANCELLED, reason="Booking expired", user=None)
                    change_plot_status(plot=plot, new_status=Plot.Status.AVAILABLE, reason="Booking expired", user=None)
                booking.status = PlotBooking.Status.EXPIRED
                booking.save(update_fields=["status", "updated_at"])
                processed += 1
        except Exception:
            logger.exception("Booking expiry failed for row id=%s", booking_id)
    return processed


def _run_reminders_if_due():
    global _last_reminder_run_at
    now = timezone.now()
    interval = max(0, int(getattr(settings, "REMINDER_INTERVAL_SECONDS", 60)))
    if _last_reminder_run_at is not None and (now - _last_reminder_run_at).total_seconds() < interval:
        return False
    _last_reminder_run_at = now
    try:
        process_due_reminders()
    except Exception:
        logger.exception("Reminder scan failed")
    return True


def _resolve_task(task_path):
    parts = task_path.split(".")
    for index in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:index]))
        except ImportError:
            continue
        target = module
        for name in parts[index:]:
            target = getattr(target, name)
        return target
    raise LookupError(f"Unable to resolve task {task_path!r}")


class DatabaseTaskBackend(BaseTaskBackend):
    supports_defer = True
    supports_async_task = True
    supports_get_result = True
    supports_priority = True

    def enqueue(self, task, args, kwargs):
        self.validate_task(task)
        now = timezone.now()
        record = TaskRecord.objects.create(
            id=get_random_string(32),
            task_path=task.module_path,
            queue_name=task.queue_name,
            priority=task.priority,
            args=normalize_json(args),
            kwargs=normalize_json(kwargs),
            run_after=task.run_after or now,
            enqueued_at=now,
        )
        result = self._result_from_record(record, task)
        task_enqueued.send(type(self), task_result=result)
        return result

    def get_result(self, result_id):
        try:
            record = TaskRecord.objects.get(pk=result_id)
        except TaskRecord.DoesNotExist:
            raise TaskResultDoesNotExist(result_id) from None
        return self._result_from_record(record)

    def claim_due_task(self, worker_id):
        now = timezone.now()
        with transaction.atomic():
            stale_before = now - timedelta(
                seconds=max(1, int(getattr(settings, "TASK_RUNNING_TIMEOUT_SECONDS", 900)))
            )
            stale_queryset = TaskRecord.objects.filter(
                status=TaskRecord.Status.RUNNING,
                started_at__lt=stale_before,
            )
            if connection.vendor == "postgresql":
                stale_queryset = stale_queryset.select_for_update(skip_locked=True)
            else:
                stale_queryset = stale_queryset.select_for_update()
            max_attempts = max(1, int(getattr(settings, "TASK_MAX_ATTEMPTS", 3)))
            for stale_record in stale_queryset:
                if stale_record.attempts < max_attempts:
                    stale_record.status = TaskRecord.Status.READY
                    stale_record.run_after = now
                    stale_record.started_at = None
                    stale_record.finished_at = None
                    stale_record.error_type = None
                    stale_record.save(update_fields=(
                        "status", "run_after", "started_at", "finished_at", "error_type"
                    ))
                else:
                    stale_record.status = TaskRecord.Status.FAILED
                    stale_record.finished_at = now
                    stale_record.error_type = "worker_lost"
                    stale_record.save(update_fields=("status", "finished_at", "error_type"))

            queryset = TaskRecord.objects.filter(
                status=TaskRecord.Status.READY,
                run_after__lte=now,
            ).order_by("-priority", "enqueued_at")
            if connection.vendor == "postgresql":
                queryset = queryset.select_for_update(skip_locked=True)
            else:
                queryset = queryset.select_for_update()
            record = queryset.first()
            if record is None:
                return None
            record.status = TaskRecord.Status.RUNNING
            record.attempts += 1
            record.started_at = now
            record.last_attempted_at = now
            record.worker_ids = [*record.worker_ids, worker_id]
            record.save(update_fields=(
                "status", "attempts", "started_at", "last_attempted_at", "worker_ids"
            ))
            return record

    def run_once(self, worker_id):
        _run_reminders_if_due()
        record = self.claim_due_task(worker_id)
        if record is None:
            return False
        task = _resolve_task(record.task_path)
        task_result = self._result_from_record(record, task)
        task_started.send(type(self), task_result=task_result)
        try:
            if task.takes_context:
                value = task.call(TaskContext(task_result=task_result), *record.args, **record.kwargs)
            else:
                value = task.call(*record.args, **record.kwargs)
            TaskRecord.objects.filter(pk=record.pk).update(
                status=TaskRecord.Status.SUCCESSFUL,
                finished_at=timezone.now(),
                return_value=normalize_json(value),
                error_type=None,
            )
        except Exception as error:
            max_attempts = max(1, int(getattr(settings, "TASK_MAX_ATTEMPTS", 3)))
            retry = record.attempts < max_attempts
            TaskRecord.objects.filter(pk=record.pk).update(
                status=TaskRecord.Status.READY if retry else TaskRecord.Status.FAILED,
                run_after=timezone.now() + timedelta(
                    seconds=max(0, int(getattr(settings, "TASK_RETRY_DELAY_SECONDS", 60)))
                ) if retry else record.run_after,
                finished_at=None if retry else timezone.now(),
                error_type=f"{type(error).__module__}.{type(error).__qualname__}",
            )
        finally:
            finished = self.get_result(record.pk)
            task_finished.send(type(self), task_result=finished)
        return True

    @staticmethod
    def _result_from_record(record, task=None):
        task = task or _resolve_task(record.task_path)
        result = TaskResult(
            task=task,
            id=record.pk,
            status=TaskResultStatus(record.status),
            enqueued_at=record.enqueued_at,
            started_at=record.started_at,
            last_attempted_at=record.last_attempted_at,
            finished_at=record.finished_at,
            args=record.args,
            kwargs=record.kwargs,
            backend="default",
            errors=(
                [TaskError(exception_class_path=record.error_type, traceback="")]
                if record.error_type else []
            ),
            worker_ids=record.worker_ids,
        )
        object.__setattr__(result, "_return_value", record.return_value)
        return result


def get_database_backend():
    from django.tasks import task_backends

    return task_backends["default"]
