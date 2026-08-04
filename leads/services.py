from django.db import transaction

from organizations.models import Organization, OrganizationMembership
from leads.models import FollowUpCall, Lead


def assign_leads_round_robin(organization_id, lead_ids=None):
    """Assign unassigned leads evenly, safely across concurrent requests."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        telecallers = list(OrganizationMembership.objects.filter(
            organization=organization,
            role=OrganizationMembership.Role.TELECALLER,
            is_active=True,
        ).order_by("id"))
        if not telecallers:
            return []
        leads = Lead.objects.select_for_update().filter(
            organization=organization,
            assigned_membership__isnull=True,
        ).order_by("id")
        if lead_ids is not None:
            leads = leads.filter(id__in=lead_ids)
        leads = list(leads)
        if not leads:
            return []
        cursor = next((index for index, member in enumerate(telecallers) if member.id == organization.round_robin_cursor), -1)
        followups = []
        for lead in leads:
            cursor = (cursor + 1) % len(telecallers)
            membership = telecallers[cursor]
            lead.assigned_membership = membership
            lead.save(update_fields=["assigned_membership", "updated_at"])
            followups.append(FollowUpCall(
                organization=organization,
                lead=lead,
                telecaller_membership=membership,
                note="",
                outcome="",
                called_at=None,
            ))
        organization.round_robin_cursor = telecallers[cursor].id
        organization.save(update_fields=["round_robin_cursor"])
        FollowUpCall.objects.bulk_create(followups)
        return leads