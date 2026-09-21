from .models import FollowUpCall, FollowUpReminder, Lead , Sitevisit , SitevisitReschedule


def membership_to_dict(membership):
    if not membership:
        return None
    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "email": membership.user.email,
        "name": membership.user.get_full_name(),
        "role": membership.role,
    }


def follow_up_to_dict(follow_up: FollowUpCall) -> dict:
    try:
        reminder = follow_up.reminder
    except FollowUpReminder.DoesNotExist:
        reminder = None
    return {
        "id": follow_up.id,
        "lead_id": follow_up.lead_id,
        "telecaller": membership_to_dict(follow_up.telecaller_membership),
        "note": follow_up.note,
        "outcome": follow_up.outcome,
        "status": follow_up.status,
        "next_follow_up": follow_up.next_follow_up.isoformat() if follow_up.next_follow_up else None,
        "reminder_sent": follow_up.reminder_sent,
        "reminder": (
            {
                "id": reminder.id,
                "event_type": reminder.event_type,
                "status": reminder.status,
                "scheduled_for": reminder.scheduled_for.isoformat(),
            }
            if reminder else None
        ),
        "called_at": follow_up.called_at.isoformat() if follow_up.called_at else None,
        "created_at": follow_up.created_at.isoformat(),
    }


def manual_call_log_to_dict(call: FollowUpCall, request=None) -> dict:
    """Serialize the confirmed FR-P6-08 manual call-log contract."""
    recording_url = None
    if call.call_recording:
        recording_url = call.call_recording.url
        if request is not None:
            recording_url = request.build_absolute_uri(recording_url)
    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "caller": membership_to_dict(call.telecaller_membership),
        "disposition": call.outcome,
        "notes": call.note,
        "call_timestamp": call.called_at.isoformat(),
        "call_recording_url": recording_url,
        "next_follow_up": call.next_follow_up.isoformat() if call.next_follow_up else None,
        "created_at": call.created_at.isoformat(),
    }


def call_queue_item_to_dict(call: FollowUpCall) -> dict:
    """Serialize one current call attempt for the FR-P6-01 queue."""
    return {
        "id": call.id,
        "lead": {
            "id": call.lead_id,
            "full_name": call.lead.full_name,
            "phone": call.lead.phone,
            "email": call.lead.email,
            "source": call.lead.source,
        },
        "telecaller": membership_to_dict(call.telecaller_membership),
        "status": call.status,
        "outcome": call.outcome,
        "next_follow_up": call.next_follow_up.isoformat() if call.next_follow_up else None,
        "called_at": call.called_at.isoformat() if call.called_at else None,
        "is_pending_attempt": call.called_at is None,
        "created_at": call.created_at.isoformat(),
    }
    
def site_visit_to_dict(site_visit: Sitevisit, include_history=False) -> dict:
    lead = site_visit.lead
    data = {
        "id": site_visit.id,
        "site_visit_id": site_visit.id,
        "organization_id": site_visit.organization_id,
        "lead": {
            "id": lead.id,
            "name": lead.full_name,
            "email": lead.email,
            "phone": lead.phone,
            "alt_phone": lead.alt_phone,
            "occupation": lead.occupation,
            "address": lead.address,
            "source": lead.source,
        },
        "executive": membership_to_dict(site_visit.executive_membership),
        "visit_date": site_visit.visit_date.isoformat() if site_visit.visit_date else None,
        "visit_time": site_visit.visit_time.isoformat() if site_visit.visit_time else None,
        "duration_minutes": site_visit.duration_minutes,
        "site": site_visit.site,
        "location": site_visit.location,
        "customer_preference": site_visit.customer_preference,
        "notes": site_visit.notes,
        "status": site_visit.status,
        "outcome": site_visit.outcome,
        "interest_level": site_visit.interest_level,
        "remarks": site_visit.remarks,
        "cancellation_reason": site_visit.cancellation_reason,
        "cancellation_notes": site_visit.cancellation_notes,
        "created_by": (
            {
                "id": site_visit.created_by_id,
                "email": site_visit.created_by.email,
                "name": site_visit.created_by.get_full_name(),
            }
            if site_visit.created_by_id else None
        ),
        "created_at": site_visit.created_at.isoformat() if site_visit.created_at else None,
        "updated_at": site_visit.updated_at.isoformat() if site_visit.updated_at else None,
    }
    if include_history:
        data["reschedule_history"] = [
            reschedule_sitevisit_to_dict(reschedule, site_visit=site_visit)
            for reschedule in site_visit.reschedules.all()
        ]
    return data

def reschedule_sitevisit_to_dict(
    rescheduled_site_visit: SitevisitReschedule,
    site_visit=None,
) -> dict:
    sitevisit = site_visit or rescheduled_site_visit.site_visit
    lead = sitevisit.lead
    return {
        "id": rescheduled_site_visit.id,
        "organization_id": sitevisit.organization_id,
        "site_visit_id": sitevisit.id,
        "lead": {
            "id": lead.id,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "full_name": lead.full_name,
            "email": lead.email,
            "phone": lead.phone,
            "alt_phone": lead.alt_phone,
            "occupation": lead.occupation,
            "address": lead.address,
            "source": lead.source,
        },
        "old_date": rescheduled_site_visit.old_date,
        "old_time": rescheduled_site_visit.old_time,
        "new_date": rescheduled_site_visit.new_date,
        "new_time": rescheduled_site_visit.new_time,
        "reason": rescheduled_site_visit.reason,
        "rescheduled_at": rescheduled_site_visit.rescheduled_at,
    }


def lead_to_dict(lead: Lead, include_follow_ups=False , latest_follow_up_status=None) -> dict:
    data = {
        "id": lead.id,
        "organization": lead.organization.slug,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": lead.full_name,
        "email": lead.email,
        "phone": lead.phone,
        "source": lead.source,
        "alt_phone": lead.alt_phone,
        "occupation": lead.occupation,
        "address": lead.address,
        "city": lead.city,
        "score": lead.score,
        "status": latest_follow_up_status or lead.status,
        "tags": list(lead.tags.values_list("tag_name", flat=True)),
        # return only the membership name (or None)
        "assigned_membership": (membership_to_dict(lead.assigned_membership) or {}).get("name"),
        "needs_reassignment": bool(lead.assigned_membership_id and not lead.assigned_membership.is_active),
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }
    if include_follow_ups:
        data["follow_up_calls"] = [follow_up_to_dict(call) for call in lead.follow_up_calls.select_related("telecaller_membership__user").all()]
        data["status_history"] = [
            {"old_status": item.old_status, "new_status": item.new_status, "changed_by": item.changed_by_id, "created_at": item.created_at.isoformat()}
            for item in lead.status_history.select_related("changed_by").all()
        ]
        data["assignment_history"] = [
            {"assigned_from_id": item.assigned_from_id, "assigned_to_id": item.assigned_to_id, "reason": item.reason, "assigned_by": item.assigned_by_id, "created_at": item.created_at.isoformat()}
            for item in lead.assignment_history.select_related("assigned_from", "assigned_to", "assigned_by").all()
        ]
    return data
