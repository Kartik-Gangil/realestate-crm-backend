from .models import FollowUpReminder
from system_settings.services import get_system_parameter


FOLLOW_UP_REMINDER_EVENT = "telecalling.follow_up_due"
SITE_VISIT_REMINDER_DAYS_PARAMETER = "site_visit_reminder_days"


def get_site_visit_reminder_days(organization, *, project=None):
    """EC-P2-01 consumer: always read the current project parameter via cache-aside."""
    return get_system_parameter(
        organization,
        SITE_VISIT_REMINDER_DAYS_PARAMETER,
        default=1,
        project=project,
    )


def sync_follow_up_reminder(call):
    """Create/update the Phase 14 outbox event for a scheduled follow-up."""
    if call.next_follow_up is None:
        FollowUpReminder.objects.filter(
            follow_up=call,
            status=FollowUpReminder.Status.PENDING,
        ).update(status=FollowUpReminder.Status.CANCELLED)
        return None

    reminder, _created = FollowUpReminder.objects.update_or_create(
        follow_up=call,
        defaults={
            "organization": call.organization,
            "recipient_membership": call.telecaller_membership,
            "scheduled_for": call.next_follow_up,
            "event_type": FOLLOW_UP_REMINDER_EVENT,
            "status": FollowUpReminder.Status.PENDING,
            "payload": {
                "organization_id": call.organization_id,
                "lead_id": call.lead_id,
                "follow_up_id": call.id,
                "recipient_membership_id": call.telecaller_membership_id,
                "scheduled_for": call.next_follow_up.isoformat(),
            },
            "dispatched_at": None,
        },
    )
    if call.reminder_sent:
        call.reminder_sent = False
        call.save(update_fields=["reminder_sent"])
    return reminder
