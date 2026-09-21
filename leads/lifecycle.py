from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Lead, LeadAssignmentHistory, LeadStatusHistory


LEAD_STATUS_TRANSITIONS = {
    "new": {"contacted", "lost"},
    "contacted": {"interested", "lost"},
    "interested": {"site_visit_scheduled", "lost"},
    "site_visit_scheduled": {"site_visit_completed", "lost"},
    "site_visit_completed": {"converted", "lost"},
    "converted": set(),
    "lost": set(),
}


@transaction.atomic
def transition_lead_status(*, lead_id, new_status, actor, organization):
    lead = Lead.all_objects.select_for_update().get(pk=lead_id, organization=organization)
    if new_status not in LEAD_STATUS_TRANSITIONS:
        raise ValidationError({"status": "Select a valid lead status."})
    if new_status not in LEAD_STATUS_TRANSITIONS.get(lead.status, set()):
        raise ValidationError({"status": f"Cannot change a {lead.status} lead to {new_status}."})
    old_status = lead.status
    lead.status = new_status
    lead.save(update_fields=["status", "updated_at"])
    LeadStatusHistory.objects.create(lead=lead, old_status=old_status, new_status=new_status, changed_by=actor)
    if new_status == "converted":
        from customers.services import create_customer_from_lead
        create_customer_from_lead(lead=lead)
    return lead


@transaction.atomic
def assign_lead(*, lead_id, membership, reason, actor, organization):
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for every assignment."})
    lead = Lead.all_objects.select_for_update().get(pk=lead_id, organization=organization)
    if membership is not None and (membership.organization_id != organization.id or not membership.is_active):
        raise ValidationError({"telecaller_membership": "Use an active membership in this organization."})
    previous = lead.assigned_membership
    if previous_id := getattr(previous, "id", None):
        if membership is not None and previous_id == membership.id:
            raise ValidationError({"telecaller_membership": "Lead is already assigned to this user."})
    lead.assigned_membership = membership
    lead.save(update_fields=["assigned_membership", "updated_at"])
    LeadAssignmentHistory.objects.create(
        lead=lead, assigned_from=previous, assigned_to=membership, reason=reason, assigned_by=actor
    )
    return lead
