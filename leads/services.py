from pathlib import Path

from django.db import transaction
from django.db.models import Case, IntegerField, OuterRef, Subquery, Value, When
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from organizations.models import Organization, OrganizationMembership
from leads.models import FollowUpCall, Lead
from leads.reminders import sync_follow_up_reminder
from system_settings.master_data import (
    CONNECTED_CALL_DISPOSITION_CODES,
    FOLLOW_UP_REQUIRED_DISPOSITION_CODES,
    validate_call_disposition,
)
from .lifecycle import LEAD_STATUS_TRANSITIONS, transition_lead_status


CALL_QUEUE_TABS = {"assigned", "pending", "connected", "follow_ups"}
MAX_CALL_RECORDING_SIZE_BYTES = 25 * 1024 * 1024
CALL_RECORDING_CONTENT_TYPES = {
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
    ".aac": {"audio/aac", "audio/x-aac"},
}

# FR-P6 exit-gate integration: map a completed external call to the next
# meaningful lead lifecycle state without allowing an automatic regression.
DISPOSITION_LEAD_STATUS = {
    "interested": "interested",
    "callback_later": "contacted",
    "busy": "contacted",
    "no_answer": "contacted",
    "switched_off": "contacted",
    "wrong_number": "lost",
    "dnd": "lost",
    "already_purchased": "lost",
}


def validate_call_recording(recording):
    """FR-P6-08: enforce the confirmed 25 MB audio recording contract."""
    if recording is None:
        return
    suffix = Path(recording.name).suffix.lower()
    if suffix not in CALL_RECORDING_CONTENT_TYPES:
        raise ValidationError({
            "call_recording": "Use an MP3, WAV, M4A, or AAC audio file."
        })
    if recording.size > MAX_CALL_RECORDING_SIZE_BYTES:
        raise ValidationError({"call_recording": "The recording must not exceed 25 MB."})
    if getattr(recording, "content_type", "") not in CALL_RECORDING_CONTENT_TYPES[suffix]:
        raise ValidationError({
            "call_recording": "The uploaded file content type does not match its audio format."
        })


def _auto_update_lead_status(*, lead, disposition, actor, organization):
    """Advance a lead from a disposition without ever moving it backwards."""
    target_status = DISPOSITION_LEAD_STATUS[disposition]
    current_status = lead.status
    if current_status == target_status:
        return lead

    # An "interested" disposition from a brand-new lead must still honour
    # the Phase 5 state machine's mandatory contacted step.
    path = [target_status]
    if current_status == "new" and target_status == "interested":
        path = ["contacted", "interested"]

    for next_status in path:
        if next_status not in LEAD_STATUS_TRANSITIONS.get(current_status, set()):
            return lead
        lead = transition_lead_status(
            lead_id=lead.id,
            new_status=next_status,
            actor=actor,
            organization=organization,
        )
        current_status = next_status
    return lead


@transaction.atomic
def log_manual_call(
    *, access, lead, disposition, notes, call_timestamp=None,
    next_follow_up=None, call_recording=None,
):
    """FR-P6-02/04/05/06/08: persist one completed external phone call."""
    membership = access.membership
    if membership is None or membership.role != OrganizationMembership.Role.TELECALLER:
        raise PermissionDenied("Only a telecaller may submit a manual call log.")
    if lead.assigned_membership_id != membership.id:
        raise PermissionDenied("You can only log calls for leads assigned to you.")
    if not disposition:
        raise ValidationError({"disposition": "This field is required."})
    notes = str(notes or "").strip()
    if not notes:
        raise ValidationError({"notes": "This field is required."})
    validate_call_disposition(access.organization, disposition)
    if disposition in FOLLOW_UP_REQUIRED_DISPOSITION_CODES and next_follow_up is None:
        raise ValidationError({
            "next_follow_up": "A follow-up date and time is required for this disposition."
        })
    validate_call_recording(call_recording)

    call = FollowUpCall.objects.select_for_update().filter(
        organization=access.organization,
        lead=lead,
        telecaller_membership=membership,
        called_at__isnull=True,
    ).order_by("created_at", "id").first()
    created = call is None
    if created:
        call = FollowUpCall(
            organization=access.organization,
            lead=lead,
            telecaller_membership=membership,
        )
    call.outcome = disposition
    call.note = notes
    call.called_at = call_timestamp or timezone.now()
    call.next_follow_up = next_follow_up
    if call_recording is not None:
        call.call_recording = call_recording
    call.full_clean()
    call.save()
    sync_follow_up_reminder(call)
    _auto_update_lead_status(
        lead=lead,
        disposition=disposition,
        actor=membership.user,
        organization=access.organization,
    )
    return call, created


def get_call_queue(access, *, tab="assigned"):
    """Return the FR-P6-01 queue, scoped to the requesting organization/user.

    FR-P6-01 precedence is pending attempt, scheduled follow-up time, creation
    time, then row ID. Lead score is explicitly out of scope.
    """
    if tab not in CALL_QUEUE_TABS:
        raise ValidationError({"tab": f"Use one of: {', '.join(sorted(CALL_QUEUE_TABS))}."})

    latest_attempt_id = (
        FollowUpCall.objects.filter(
            organization=access.organization,
            lead_id=OuterRef("lead_id"),
        )
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    queue = (
        FollowUpCall.objects.filter(
            organization=access.organization,
            id=Subquery(latest_attempt_id),
        )
        .select_related("lead", "telecaller_membership__user")
    )

    if not access.can_view_all_leads:
        queue = queue.filter(
            telecaller_membership=access.membership,
            lead__assigned_membership=access.membership,
        )

    if tab == "pending":
        queue = queue.filter(called_at__isnull=True)
    elif tab == "connected":
        queue = queue.filter(
            called_at__isnull=False,
            outcome__in=CONNECTED_CALL_DISPOSITION_CODES,
        )
    elif tab == "follow_ups":
        queue = queue.filter(next_follow_up__isnull=False)

    return queue.annotate(
        pending_attempt_order=Case(
            When(called_at__isnull=True, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        missing_follow_up_order=Case(
            When(next_follow_up__isnull=True, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by(
        "pending_attempt_order",
        "missing_follow_up_order",
        "next_follow_up",
        "created_at",
        "id",
    )


def get_team_call_analytics(access):
    """Build organization-scoped FR-P6-07 queue and performance analytics."""
    telecallers = list(
        OrganizationMembership.objects.filter(
            organization=access.organization,
            role=OrganizationMembership.Role.TELECALLER,
            is_active=True,
        )
        .select_related("user")
        .order_by("id")
    )
    telecaller_ids = [member.id for member in telecallers]
    per_caller = {
        member.id: {
            "telecaller": {
                "id": member.id,
                "user_id": member.user_id,
                "email": member.user.email,
                "name": member.user.get_full_name(),
                "role": member.role,
            },
            "queue_count": 0,
            "pending_count": 0,
            "completed_calls": 0,
            "connected_calls": 0,
            "follow_up_count": 0,
        }
        for member in telecallers
    }

    latest_attempt_id = (
        FollowUpCall.objects.filter(
            organization=access.organization,
            lead_id=OuterRef("lead_id"),
        )
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    queue_rows = FollowUpCall.objects.filter(
        organization=access.organization,
        telecaller_membership_id__in=telecaller_ids,
        id=Subquery(latest_attempt_id),
    ).values("telecaller_membership_id", "called_at", "next_follow_up")

    totals = {
        "queue_count": 0,
        "pending_count": 0,
        "completed_calls": 0,
        "connected_calls": 0,
        "follow_up_count": 0,
    }
    for row in queue_rows:
        metrics = per_caller[row["telecaller_membership_id"]]
        metrics["queue_count"] += 1
        totals["queue_count"] += 1
        if row["called_at"] is None:
            metrics["pending_count"] += 1
            totals["pending_count"] += 1
        if row["next_follow_up"] is not None:
            metrics["follow_up_count"] += 1
            totals["follow_up_count"] += 1

    disposition_counts = {}
    completed_rows = FollowUpCall.objects.filter(
        organization=access.organization,
        telecaller_membership_id__in=telecaller_ids,
        called_at__isnull=False,
    ).values("telecaller_membership_id", "outcome")
    for row in completed_rows:
        metrics = per_caller[row["telecaller_membership_id"]]
        metrics["completed_calls"] += 1
        totals["completed_calls"] += 1
        if row["outcome"] in CONNECTED_CALL_DISPOSITION_CODES:
            metrics["connected_calls"] += 1
            totals["connected_calls"] += 1
        if row["outcome"]:
            disposition_counts[row["outcome"]] = disposition_counts.get(row["outcome"], 0) + 1

    return {
        "team": {"telecaller_count": len(telecallers)},
        "totals": totals,
        "by_disposition": dict(sorted(disposition_counts.items())),
        "telecallers": list(per_caller.values()),
    }


@transaction.atomic
def redistribute_call_queue(*, access, call_ids, telecaller_membership_id):
    """Atomically move idle current queue items and their leads to one telecaller."""
    target = OrganizationMembership.objects.select_for_update().filter(
        pk=telecaller_membership_id,
        organization=access.organization,
        role=OrganizationMembership.Role.TELECALLER,
        is_active=True,
    ).select_related("user").first()
    if target is None:
        raise ValidationError({
            "telecaller_membership_id": "Select an active telecaller in this organization."
        })

    latest_attempt_id = (
        FollowUpCall.objects.filter(
            organization=access.organization,
            lead_id=OuterRef("lead_id"),
        )
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    calls = list(
        FollowUpCall.objects.select_for_update()
        .select_related("lead")
        .filter(
            organization=access.organization,
            id__in=call_ids,
            id=Subquery(latest_attempt_id),
        )
        .order_by("id")
    )
    if len(calls) != len(call_ids):
        raise ValidationError({"call_ids": "Every call must be a current queue item in this organization."})
    if any(call.called_at is not None for call in calls):
        raise ValidationError({"call_ids": "Only pending calls can be redistributed."})

    lead_ids = [call.lead_id for call in calls]
    leads = list(Lead.objects.select_for_update().filter(
        organization=access.organization,
        id__in=lead_ids,
    ))
    if len(leads) != len(lead_ids):
        raise ValidationError({"call_ids": "Every queue item must reference a lead in this organization."})

    FollowUpCall.objects.filter(id__in=call_ids).update(telecaller_membership=target)
    Lead.objects.filter(id__in=lead_ids).update(assigned_membership=target, updated_at=timezone.now())
    return target, calls


def assign_leads_round_robin(organization_id, lead_ids=None):
    """Assign unassigned leads evenly, safely across concurrent requests."""

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)

        telecallers = list(
            OrganizationMembership.objects.filter(
                organization=organization,
                role=OrganizationMembership.Role.TELECALLER,
                is_active=True,
            ).order_by("id")
        )

        if not telecallers:
            return []

        # Latest follow-up status for each lead
        latest_status = (
            FollowUpCall.objects.filter(
                lead=OuterRef("pk")
            )
            .order_by("-created_at")
            .values("status")[:1]
        )

        leads = (
            Lead.objects.select_for_update()
            .filter(
                organization=organization,
                assigned_membership__isnull=True,
            )
            .annotate(previous_status=Subquery(latest_status))
            .order_by("id")
        )

        if lead_ids is not None:
            leads = leads.filter(id__in=lead_ids)

        leads = list(leads)

        if not leads:
            return []

        cursor = next(
            (
                index
                for index, member in enumerate(telecallers)
                if member.id == organization.round_robin_cursor
            ),
            -1,
        )

        followups = []

        for lead in leads:
            cursor = (cursor + 1) % len(telecallers)
            membership = telecallers[cursor]

            lead.assigned_membership = membership
            lead.save(update_fields=["assigned_membership", "updated_at"])

            followups.append(
                FollowUpCall(
                    organization=organization,
                    lead=lead,
                    telecaller_membership=membership,
                    status=lead.previous_status or "New",
                    note="",
                    outcome="",
                    called_at=None,
                )
            )

        organization.round_robin_cursor = telecallers[cursor].id
        organization.save(update_fields=["round_robin_cursor"])

        FollowUpCall.objects.bulk_create(followups)

        return leads
