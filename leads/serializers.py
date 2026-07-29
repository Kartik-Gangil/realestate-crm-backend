from .models import FollowUpCall, Lead


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
    return {
        "id": follow_up.id,
        "lead_id": follow_up.lead_id,
        "telecaller": membership_to_dict(follow_up.telecaller_membership),
        "note": follow_up.note,
        "outcome": follow_up.outcome,
        "called_at": follow_up.called_at.isoformat(),
        "created_at": follow_up.created_at.isoformat(),
    }


def lead_to_dict(lead: Lead, include_follow_ups=False) -> dict:
    data = {
        "id": lead.id,
        "organization": lead.organization.slug,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": lead.full_name,
        "email": lead.email,
        "phone": lead.phone,
        "source": lead.source,
        "status": lead.status,
        "next_follow_up": lead.next_follow_up.isoformat() if lead.next_follow_up else None,
        "assigned_membership": membership_to_dict(lead.assigned_membership),
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }
    if include_follow_ups:
        data["follow_up_calls"] = [follow_up_to_dict(call) for call in lead.follow_up_calls.select_related("telecaller_membership__user").all()]
    return data