import json

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import OuterRef, Subquery

from organizations.models import Organization, OrganizationMembership
from leads.models import FollowUpCall, Lead, LeadAssignmentHistory, LeadStatusHistory
from system_settings.audit import log_bulk_audit
from .constants import LEAD_STATUS_NEW


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
                    status=lead.previous_status or LEAD_STATUS_NEW,
                    note="",
                    outcome="",
                    called_at=None,
                )
            )

        organization.round_robin_cursor = telecallers[cursor].id
        organization.save(update_fields=["round_robin_cursor"])

        FollowUpCall.objects.bulk_create(followups)
        log_bulk_audit(
            module="leads", action="bulk_create", instances=followups,
            organization=organization, changed_values={"fields": ["lead", "telecaller_membership"]},
        )

        return leads


def _purge_lead_history_for_deletion(lead_ids, *, using):
    """Delete protected lead history only as part of an approved lead delete."""
    LeadAssignmentHistory.objects.using(using).filter(lead_id__in=lead_ids)._raw_delete(using)
    LeadStatusHistory.objects.using(using).filter(lead_id__in=lead_ids)._raw_delete(using)


def delete_leads_with_history(*, leads, request=None, organization=None, project=None):
    """Delete non-converted leads atomically after recording their old values."""
    lead_ids = [lead.pk for lead in leads]
    if not lead_ids:
        return 0
    using = Lead.objects.db
    with transaction.atomic(using=using):
        locked_leads = list(
            Lead.objects.using(using).select_for_update().filter(
                pk__in=lead_ids,
                **({"organization": organization} if organization is not None else {}),
                **({"project": project} if project is not None else {}),
            )
        )
        if len(locked_leads) != len(set(lead_ids)):
            return 0
        converted = [lead.pk for lead in locked_leads if lead.lifecycle_status == "converted"]
        if converted:
            raise ValidationError({"detail": "Converted leads cannot be deleted."})
        audit_snapshots = []
        for lead in locked_leads:
            before = {
                field.name: field.value_from_object(lead)
                for field in lead._meta.concrete_fields
            }
            audit_snapshots.append((lead, json.loads(json.dumps(before, cls=DjangoJSONEncoder))))
        _purge_lead_history_for_deletion(lead_ids, using=using)
        Lead.objects.using(using).filter(pk__in=lead_ids).delete()
        for lead, before in audit_snapshots:
            # Write after the model delete so the explicit organization-scoped
            # record is newer than the generic post_delete audit row, while
            # retaining the lead's old values and organization context.
            log_bulk_audit(
                request=request,
                module="leads",
                action="delete",
                record_ids=[lead.pk],
                organization=organization or lead.organization,
                project=project or lead.project,
                before=before,
                target_type="Lead",
            )
    return len(locked_leads)
