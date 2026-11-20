import pandas as pd
import io
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.db.models import Avg, Count, Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from organizations.models import Organization, OrganizationMembership
from organizations.services import apply_data_scope, get_organization_access, get_project_context, has_permission
from system_settings.models import MasterData
from system_settings.services import UnknownSystemParameter, get_system_parameter
from .models import FollowUpCall, Lead, LeadAssignmentHistory, LeadImportBatch, LeadStatusHistory, LeadTag, Sitevisit, SitevisitReschedule
from .constants import (
    CONVERTED_LEAD_IMMUTABLE_FIELDS,
    LEAD_AUTOMATIC_TRANSITIONS,
    LEAD_STATUS_ALIASES,
    LEAD_STATUS_LABELS,
    LEAD_STATUS_NEW,
    LEAD_STATUS_ORDER,
    LEAD_STATUS_TRANSITIONS,
)
from .serializers import (
    follow_up_to_dict,
    lead_to_dict,
    reschedule_sitevisit_to_dict,
    site_visit_to_dict,
)
from .services import assign_leads_round_robin, delete_leads_with_history
from .duplicate import score_duplicates
from .merge import MERGE_FIELDS, merge_into_existing
from .phone import normalize_phone
from system_settings.audit import log_bulk_audit
from core.endpoint import crm_endpoint
from django.db.models import OuterRef, Subquery
from django.utils import timezone

CSV_HEADER_ALIASES = {
    "first_name": "first_name", "firstname": "first_name", "first": "first_name",
    "last_name": "last_name", "lastname": "last_name", "last": "last_name",
    "full_name": "full_name", "fullname": "full_name", "name": "full_name",
    "email": "email", "email_address": "email",
    "phone": "phone", "phone_number": "phone", "mobile": "phone",
    "mobile_number": "phone", "contact_number": "phone",
    "source": "source",
    "platform": "source",
    "assigned_membership": "assigned_membership", "assigned_membership_id": "assigned_membership",
    "assignee_id": "assigned_membership",
}


def _normalise_csv_header(header):
    return "_".join(header.strip().lower().replace("-", " ").split())


def _csv_row_payload(row):
    payload = {}
    for header, value in row.items():
        if header is None:
            continue
        field = CSV_HEADER_ALIASES.get(_normalise_csv_header(header))
        value = value.strip() if value else ""
        if field and value:
            payload[field] = value
    if "full_name" in payload:
        name_parts = payload.pop("full_name").split(None, 1)
        payload.setdefault("first_name", name_parts[0] if name_parts else "")
        if len(name_parts) == 2:
            payload.setdefault("last_name", name_parts[1])
    payload.setdefault("source", Lead.Source.WEBSITE)
    return payload


def _parse_datetime(value, field_name):
    if value is None:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({field_name: "Use an ISO 8601 datetime."})
    return parsed


def _parse_date(value, field_name):
    if value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({field_name: "Use an ISO 8601 date (YYYY-MM-DD)."})
    return parsed


def _parse_time(value, field_name):
    if value is None:
        return None
    parsed = parse_time(value)
    if parsed is None:
        raise ValidationError({field_name: "Use an ISO 8601 time (HH:MM[:SS])."})
    return parsed


def _site_visits_for_access(access, leads=None, project=None):
    visits = Sitevisit.objects.filter(
        organization=access.organization,
    ).select_related(
        "organization", "lead", "executive_membership__user", "created_by"
    ).prefetch_related("reschedules")
    # A visit is historical activity. Listing it must not depend on the lead's
    # current assignment, otherwise unassigning a lead erases the visit from
    # the telecaller who previously handled it. Callers that are validating a
    # lead relationship (for example inventory booking) may still pass a
    # restricted lead queryset explicitly.
    if leads is not None:
        visits = visits.filter(lead__in=leads)
    if leads is None and not access.can_view_all_leads:
        # Telecallers and other non-manager users keep access to visits they
        # historically handled, even after the linked lead is unassigned.
        visits = visits.filter(
            Q(executive_membership=access.membership)
            | Q(created_by=access.membership.user)
        )
    if project is not None:
        # Older visits may not have a project reference yet. They remain
        # project-safe when their linked lead belongs to the active project.
        visits = visits.filter(Q(project=project) | Q(project__isnull=True, lead__project=project))
    return apply_data_scope(
        visits,
        access,
        module="site_visits",
        membership_lookups=("executive_membership", "lead__assigned_membership"),
        user_lookups=("created_by",),
    )


def _schedule_validation(visit_date, visit_time, organization, project):
    errors = {}
    if visit_date is None:
        errors["visit_date"] = "This field is required."
    if visit_time is None:
        errors["visit_time"] = "This field is required."
    if visit_date:
        today = timezone.localdate()
        try:
            max_days_ahead = int(get_system_parameter(
                organization, "site_visit_max_days_ahead", project=project
            ))
        except UnknownSystemParameter:
            max_days_ahead = 90
        if visit_date < today:
            errors["visit_date"] = "A site visit cannot be scheduled in the past."
        elif visit_date > today + timedelta(days=max_days_ahead):
            errors["visit_date"] = f"A site visit cannot be scheduled more than {max_days_ahead} days ahead."
    if errors:
        raise ValidationError(errors)


def _ensure_executive_is_available(executive, visit_date, visit_time, duration_minutes, exclude_id=None):
    """Reject overlapping non-terminal visits for the same executive."""
    requested_start = datetime.combine(visit_date, visit_time)
    requested_end = requested_start + timedelta(minutes=duration_minutes)
    visits = Sitevisit.objects.filter(
        executive_membership=executive,
        visit_date=visit_date,
    ).exclude(status__in=[Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW])
    if exclude_id is not None:
        visits = visits.exclude(pk=exclude_id)
    for existing in visits:
        if not existing.visit_time:
            continue
        existing_start = datetime.combine(existing.visit_date, existing.visit_time)
        existing_end = existing_start + timedelta(minutes=existing.duration_minutes or 60)
        if requested_start < existing_end and existing_start < requested_end:
            raise ValidationError({"executive": "The selected executive has a conflicting site visit."})


def _active_executive(organization, user):
    executive = OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        is_active=True
    ).select_related("user").first()

    if executive is None:
        raise ValidationError({
            "executive": "Authenticated user is not an active organization member."
        })

    return executive


def _active_executive_membership(organization, membership_id):
    try:
        membership_id = int(membership_id)
    except (TypeError, ValueError):
        membership_id = None
    executive = OrganizationMembership.objects.filter(
        organization=organization,
        pk=membership_id,
        is_active=True,
    ).select_related("user").first()
    if executive is None:
        raise ValidationError({"executive": "Select an active organization executive."})
    return executive


def _reschedule_site_visit(site_visit, new_date, new_time, reason=None):
    if site_visit.status in {
        Sitevisit.Status.COMPLETED, Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW,
    }:
        raise ValidationError({"status": "Completed, cancelled, and no-show visits cannot be rescheduled."})
    _schedule_validation(new_date, new_time, site_visit.organization, site_visit.project)
    reschedule = SitevisitReschedule(
        site_visit=site_visit,
        old_date=site_visit.visit_date,
        old_time=site_visit.visit_time,
        new_date=new_date,
        new_time=new_time,
        reason=reason,
    )
    reschedule.full_clean()
    reschedule.save()
    site_visit.visit_date = new_date
    site_visit.visit_time = new_time
    site_visit.status = Sitevisit.Status.RESCHEDULED
    site_visit.save(update_fields=["visit_date", "visit_time", "status", "updated_at"])
    return reschedule

def _leads_for_access(access, project=None):
    leads = Lead.objects.filter(organization=access.organization).select_related("organization", "assigned_membership__user")
    if project is not None:
        leads = leads.filter(project=project)
    return apply_data_scope(leads, access, module="leads", membership_lookups=("assigned_membership",))


def _can_edit_leads(access, project):
    user = access.membership.user if access.membership else None
    return access.is_platform or has_permission(user, access.organization, "leads.edit", project=project)


def _duplicate_matches_for_access(access, project, payload):
    matches = score_duplicates(access.organization, project, payload)
    if _can_edit_leads(access, project):
        return matches
    visible_ids = set(_leads_for_access(access, project).values_list("id", flat=True))
    limited_fields = {"score", "rule", "lead_code"}
    return [
        match if match.get("id") in visible_ids else {field: match[field] for field in limited_fields if field in match}
        for match in matches
    ]


def _require_lead_management(access, permission="leads.edit", project=None):
    user = access.membership.user if access.membership else None
    if not access.is_platform and not has_permission(user, access.organization, permission, project=project):
        raise PermissionDenied(f"Permission denied for {permission}.")


def _normalise_phone(value):
    return "".join(character for character in str(value or "") if character.isdigit())


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.add"})
def check_duplicate_lead(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    try:
        return Response({"matches": _duplicate_matches_for_access(access, project, request.data)})
    except ValidationError as error:
        return _validation_response(error)


def _apply_payload(lead, payload, organization, partial=False, save=True, project=None):
    allowed = {"first_name", "last_name", "email", "phone", "source", "assigned_membership", "alt_phone", "address", "occupation", "score", "budget_range", "preferred_location", "external_source", "external_id"}
    if not partial:
        missing = [field for field in ("first_name", "phone", "source") if field not in payload]
        if missing:
            raise ValidationError({field: "This field is required." for field in missing})
    for field in allowed & payload.keys():
        value = payload[field]
        if field in {"phone", "alt_phone"} and value:
            value = normalize_phone(value)
            if value is None:
                raise ValidationError({field: "Phone number cannot be normalized."})
        if field == "assigned_membership":
            value = OrganizationMembership.objects.filter(pk=value, organization=organization, is_active=True).first() if value else None
            if payload[field] and value is None:
                raise ValidationError({"assigned_membership": "Use an active membership in this organization."})
            field = "assigned_membership"
        setattr(lead, field, value)
    lead.organization = organization
    if project is not None:
        lead.project = project
    lead.full_clean()
    if save:
        lead.save()
    return lead


def _active_lead_master_data(project, field, code=None, default_code=None):
    requested_code = str(code if code is not None else default_code or "").strip()
    if not requested_code:
        raise ValidationError({field: "This field is required."})
    category_code = "lead_source" if field == "source" else "lead_stage"
    item = MasterData.objects.filter(
        organization_id=project.organization_id,
        project=project,
        category__code=category_code,
        code=requested_code,
        is_active=True,
    ).first()
    if item is None:
        raise ValidationError({field: f"Use an active {category_code.replace('_', ' ')} from this project."})
    return item


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.add"})
def manual_lead_create(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, permission="leads.add", project=project)
    payload = dict(request.data)
    resolution = payload.pop("resolution", None)
    merge_into = payload.pop("merge_into", None)
    if not str(payload.get("phone") or "").strip():
        return Response({"phone": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        can_edit = _can_edit_leads(access, project)
        if not can_edit and access.membership is not None:
            payload["assigned_membership"] = access.membership.id
        source_item = _active_lead_master_data(project, "source", payload.get("source"))
        status_item = _active_lead_master_data(project, "status", payload.get("status"), LEAD_STATUS_NEW)
        matches = _duplicate_matches_for_access(access, project, payload)
        if matches and resolution not in {"create_anyway", "merge"}:
            return Response({"matches": matches}, status=status.HTTP_409_CONFLICT)
        with transaction.atomic():
            if resolution == "merge":
                if not merge_into:
                    return Response({"merge_into": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
                if not can_edit:
                    target_is_visible = _leads_for_access(access, project).filter(pk=merge_into).exists()
                    if not target_is_visible:
                        return Response({"detail": "You cannot merge into a lead outside your data scope."}, status=status.HTTP_403_FORBIDDEN)
                existing = get_object_or_404(
                    Lead.objects.select_for_update(),
                    pk=merge_into,
                    organization=access.organization,
                    project=project,
                )
                lead = merge_into_existing(existing=existing, payload=payload, request=request)
                return Response(lead_to_dict(lead), status=status.HTTP_200_OK)
            lead = _apply_payload(Lead(project=project), payload, access.organization, project=project, save=False)
            lead.source = source_item.code
            lead.source_item = source_item
            lead.status = status_item
            lead.save()
            lead.save()
            if not can_edit and access.membership is not None:
                _create_pending_follow_up(lead, access.membership)
            log_bulk_audit(
                request=request,
                module="leads",
                action="create",
                instances=[lead],
                organization=access.organization,
                project=project,
                changed_values={"fields": ["lead_code", "phone", "source"]},
            )
        return Response(lead_to_dict(lead), status=status.HTTP_201_CREATED)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)


@crm_endpoint(["POST"], scope="public")
def meta_webhook(request, organization_slug):
    from .connectors import receive_meta
    organization = get_object_or_404(Organization, slug=organization_slug)
    return receive_meta(request, organization)


@crm_endpoint(["POST"], scope="public")
def google_webhook(request, organization_slug):
    from .connectors import receive_google
    organization = get_object_or_404(Organization, slug=organization_slug)
    return receive_google(request, organization)


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.sync"})
def sync_connector(request, organization_slug, connector):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, permission="leads.sync", project=project)
    from .connectors import sync
    integration_type = "meta_ads" if connector == "meta" else "google_ads"
    return sync(request, access.organization, integration_type, project)


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.add"})
def merge_leads(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, permission="leads.add", project=project)
    source_id = request.data.get("source_lead_id")
    target_id = request.data.get("target_lead_id")
    if not source_id or not target_id or str(source_id) == str(target_id):
        return Response({"detail": "Provide two different lead IDs."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            source = get_object_or_404(
                Lead.objects.filter(organization=access.organization, project=project),
                pk=source_id,
            )
            target = get_object_or_404(
                Lead.objects.select_for_update().filter(organization=access.organization, project=project),
                pk=target_id,
            )
            payload = {field: getattr(source, field) for field in MERGE_FIELDS}
            payload["assigned_membership"] = source.assigned_membership_id
            delete_leads_with_history(
                leads=[source],
                request=request,
                organization=access.organization,
                project=project,
            )
            target = merge_into_existing(existing=target, payload=payload, request=request)
    except ValidationError as error:
        return _validation_response(error)
    return Response(lead_to_dict(target), status=status.HTTP_200_OK)


def _validation_response(error):
    if hasattr(error, "message_dict"):
        details = error.message_dict
    elif hasattr(error, "messages"):
        details = {"detail": error.messages}
    else:
        details = {"detail": [str(error)]}
    return Response(details, status=status.HTTP_400_BAD_REQUEST)

def _create_pending_follow_up(lead, telecaller):
    existing = FollowUpCall.objects.filter(
        organization=lead.organization,
        lead=lead,
        telecaller_membership=telecaller,
        called_at__isnull=True,
    ).order_by("created_at", "id").first()
    if existing is not None:
        return existing
    return FollowUpCall.objects.create(organization=lead.organization, lead=lead, telecaller_membership=telecaller, note="", outcome="", called_at=None)


def _update_follow_up_result(call, payload):
    allowed = {"note", "outcome", "status", "next_follow_up", "called_at"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError({field: "This field cannot be updated." for field in unknown})
    if "note" in payload:
        call.note = str(payload["note"]).strip()
    if "outcome" in payload:
        call.outcome = payload["outcome"]
    if "status" in payload:
        call.status = payload["status"]
    if "next_follow_up" in payload:
        call.next_follow_up = _parse_datetime(payload["next_follow_up"], "next_follow_up")
    if "called_at" in payload:
        call.called_at = _parse_datetime(payload["called_at"], "called_at")
    call.full_clean()
    if call.pk:
        call.save(update_fields=["note", "outcome", "status", "next_follow_up", "called_at"])
    else:
        call.save()
    return call

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def remove_assignment_of_lead(request ,organization_slug):
    """Remove current assignments from all assigned leads."""
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, project=project)
    reason = str(request.data.get("reason", "")).strip()
    if len(reason) < 3:
        return Response({"reason": ["A reason of at least 3 characters is required."]}, status=status.HTTP_400_BAD_REQUEST)

    leads = _leads_for_access(access, project).filter(assigned_membership__isnull=False)
    with transaction.atomic():
        affected = list(leads.select_for_update())
        for lead in affected:
            previous_membership = lead.assigned_membership
            lead.assigned_membership = None
            lead.save(update_fields=["assigned_membership", "updated_at"])
            LeadAssignmentHistory.objects.create(
                lead=lead,
                organization=access.organization,
                assigned_from=previous_membership,
                assigned_to=None,
                reason=reason,
                assigned_by=request.user,
            )
        if affected:
            log_bulk_audit(
                request=request, module="leads", action="bulk_update", instances=affected,
                organization=access.organization, project=project,
                changed_values={"assigned_membership": None, "reason": reason},
            )

    return Response({
        "message": "Lead assignments reset successfully.",
        "updated_count": len(affected),
    }, status=status.HTTP_200_OK)



@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def assign_lead(request, organization_slug, lead_id):
    """Assign or reassign one organization lead to an active telecaller."""
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access)
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)
    membership_id = request.data.get("telecaller_membership", request.data.get("assigned_membership"))
    reason = str(request.data.get("reason", "")).strip()
    if not membership_id:
        return Response({"telecaller_membership": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    if len(reason) < 3:
        return Response({"reason": ["A reason is required."]}, status=status.HTTP_400_BAD_REQUEST)
    telecaller = OrganizationMembership.objects.filter(
        pk=membership_id,
        organization=access.organization,
        role=OrganizationMembership.Role.TELECALLER,
        is_active=True,
    ).select_related("user").first()
    if telecaller is None:
        return Response({"telecaller_membership": ["Use an active telecaller membership in this organization."]}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        previous_membership = lead.assigned_membership
        lead.assigned_membership = telecaller
        lead.full_clean()
        lead.save(update_fields=["assigned_membership", "updated_at"])
        LeadAssignmentHistory.objects.create(
            lead=lead,
            organization=access.organization,
            assigned_from=previous_membership,
            assigned_to=telecaller,
            reason=reason,
            assigned_by=request.user,
        )
        _create_pending_follow_up(lead, telecaller)
    return Response(lead_to_dict(lead))


def _canonical_lead_status(value):
    normalized = str(value or "").strip().lower().replace(" ", "_")
    normalized = LEAD_STATUS_ALIASES.get(normalized, normalized)
    if normalized not in LEAD_STATUS_TRANSITIONS:
        raise ValidationError({"status": "Use a valid lead status."})
    return normalized


def _record_lead_status_transition(*, lead, status_value, user, reason="", system=False):
    status_value = _canonical_lead_status(status_value)
    call = None
    with transaction.atomic():
        locked_lead = Lead.objects.select_for_update().select_related("organization", "assigned_membership").get(pk=lead.pk)
        previous_status = LEAD_STATUS_ALIASES.get(locked_lead.lifecycle_status or "new", locked_lead.lifecycle_status or "new")
        if system and previous_status == "lost":
            return None
        if system and previous_status in LEAD_STATUS_ORDER and status_value in LEAD_STATUS_ORDER:
            if LEAD_STATUS_ORDER.index(previous_status) >= LEAD_STATUS_ORDER.index(status_value):
                return None
        allowed_statuses = LEAD_STATUS_TRANSITIONS.get(previous_status, set())
        if system and previous_status in LEAD_AUTOMATIC_TRANSITIONS.get(status_value, set()):
            allowed_statuses = allowed_statuses | {status_value}
        if status_value not in allowed_statuses:
            raise ValidationError({"status": f"Cannot change lead status from '{previous_status}'."})
        locked_lead.lifecycle_status = status_value
        locked_lead.save(update_fields=["lifecycle_status", "updated_at"])
        LeadStatusHistory.objects.create(
            lead=locked_lead,
            organization=locked_lead.organization,
            old_status=previous_status,
            new_status=status_value,
            changed_by=user,
        )
        if not system:
            call = FollowUpCall.objects.create(
                organization=locked_lead.organization,
                lead=locked_lead,
                telecaller_membership=locked_lead.assigned_membership,
                note=str(reason or "").strip(),
                outcome=FollowUpCall.Outcome.CONNECTED,
                status={"interested": FollowUpCall.Status.QUALIFIED, "site_visit_scheduled": FollowUpCall.Status.SITE_VISIT, "converted": FollowUpCall.Status.WON}.get(status_value, status_value),
                called_at=timezone.now(),
            )
    return call


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.edit"})
def transition_lead_status(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, project=project)
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)
    try:
        call = _record_lead_status_transition(
            lead=lead,
            status_value=str(request.data.get("status", "")).strip(),
            user=request.user,
            reason=request.data.get("reason", ""),
        )
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(follow_up_to_dict(call), status=status.HTTP_201_CREATED)


@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.edit"})
def bulk_lead_action(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, project=project)
    lead_ids = request.data.get("lead_ids")
    action = str(request.data.get("action", "")).strip()
    if not isinstance(lead_ids, list) or not lead_ids:
        return Response({"lead_ids": ["Provide a non-empty list of lead IDs."]}, status=status.HTTP_400_BAD_REQUEST)
    leads = list(_leads_for_access(access, project).filter(pk__in=lead_ids))
    if len(leads) != len(set(lead_ids)):
        return Response({"lead_ids": ["One or more leads are not in the active project."]}, status=status.HTTP_404_NOT_FOUND)
    if action in {"assign", "delete"} and not access.is_platform and access.membership and access.membership.role not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER}:
        raise PermissionDenied("Only Managers and Admins may perform this bulk action.")
    if action == "export":
        if not access.is_platform and not has_permission(request.user, access.organization, "leads.export", project=project):
            raise PermissionDenied("Permission denied for leads.export.")
        return Response({"count": len(leads), "results": [lead_to_dict(lead) for lead in leads]})
    try:
        with transaction.atomic():
            if action == "delete":
                deleted = delete_leads_with_history(
                    leads=leads,
                    request=request,
                    organization=access.organization,
                    project=project,
                )
                return Response({"updated": deleted, "deleted": deleted})
            if action == "add_tag":
                tag_name = str(request.data.get("value", "")).strip()
                if not tag_name:
                    raise ValidationError({"value": "A tag is required."})
                for lead in leads:
                    LeadTag.objects.get_or_create(lead=lead, tag_name=tag_name)
                return Response({"updated": len(leads), "tag": tag_name})
            if action == "assign":
                membership_id = request.data.get("value")
                reason = str(request.data.get("reason", "")).strip()
                if len(reason) < 3 or not membership_id:
                    raise ValidationError({"reason": "A reason and assignee are required."})
                assignee = OrganizationMembership.objects.filter(pk=membership_id, organization=access.organization, role=OrganizationMembership.Role.TELECALLER, is_active=True).first()
                if assignee is None:
                    raise ValidationError({"value": "Use an active telecaller membership."})
                for lead in leads:
                    previous_membership = lead.assigned_membership
                    lead.assigned_membership = assignee
                    lead.save(update_fields=["assigned_membership", "updated_at"])
                    LeadAssignmentHistory.objects.create(lead=lead, organization=access.organization, assigned_from=previous_membership, assigned_to=assignee, reason=reason, assigned_by=request.user)
                return Response({"updated": len(leads), "assigned_to": assignee.id})
            if action != "status":
                raise ValidationError({"action": "Use assign, status, add_tag, export, or delete."})
            calls = [_record_lead_status_transition(lead=lead, status_value=str(request.data.get("value", "")).strip(), user=request.user, reason="Bulk status update") for lead in leads]
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response({"updated": len(calls), "results": [follow_up_to_dict(call) for call in calls]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def assigned_leads(request, organization_slug):
    """Return leads assigned to the authenticated organization member."""
    access = get_organization_access(request.user, organization_slug)
    if access.membership is None or not has_permission(request.user, access.organization, "assigned_leads.view"):
        raise PermissionDenied("The assigned-leads permission is required.")
    leads = Lead.objects.filter(
        organization=access.organization,
        assigned_membership=access.membership,
    ).select_related("organization", "assigned_membership__user")
    return Response({"count": leads.count(), "results": [lead_to_dict(lead) for lead in leads]})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_leads_csv_legacy(request, organization_slug):
    """Atomically import leads from CSV/XLS/XLSX upload."""

    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access)

    upload = request.FILES.get("file")
    if upload is None:
        return Response(
            {"file": ["Upload a file using the 'file' field."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        filename = upload.name.lower()

        if filename.endswith(".csv"):
            df = pd.read_csv(upload, dtype=str)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(upload, dtype=str, engine="openpyxl")
        elif filename.endswith(".xls"):
            df = pd.read_excel(upload, dtype=str, engine="xlrd")
        else:
            return Response(
                {"file": ["Only .csv, .xlsx and .xls files are supported."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        df = df.fillna("")
        rows = df.to_dict(orient="records")

    except Exception as error:
        return Response(
            {"file": [f"Could not read file: {error}"]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(df.columns) == 0:
        return Response(
            {"file": ["The file must include a header row."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    mapped_headers = {
        CSV_HEADER_ALIASES.get(_normalise_csv_header(header))
        for header in df.columns
        if header
    }

    if "phone" not in mapped_headers or (
        "first_name" not in mapped_headers
        and "full_name" not in mapped_headers
    ):
        return Response(
            {
                "file": [
                    "Required columns: first_name (or full_name/name) and phone."
                ]
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    leads = []
    errors = []

    for row_number, row in enumerate(rows, start=2):
        if not any(str(value).strip() for value in row.values()):
            continue

        try:
            imported_lead = _apply_payload(
                Lead(),
                _csv_row_payload(row),
                access.organization,
                save=False,
                project=project,
            )
            leads.append(imported_lead)
        except (ValidationError, ValueError, TypeError) as error:
            details = (
                error.message_dict
                if hasattr(error, "message_dict")
                else {"detail": getattr(error, "messages", [str(error)])}
            )
            errors.append(
                {
                    "row": row_number,
                    "errors": details,
                }
            )

    if errors:
        return Response(
            {"imported": 0, "errors": errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not leads:
        return Response(
            {"file": ["The file contains no lead rows."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        Lead.objects.bulk_create(leads)
        log_bulk_audit(
            request=request, module="leads", action="bulk_create", instances=leads,
            organization=access.organization, project=project,
            changed_values={"fields": ["first_name", "phone", "source"]},
        )

    return Response(
        {
            "imported": len(leads),
            "results": [lead_to_dict(lead) for lead in leads],
        },
        status=status.HTTP_201_CREATED,
    )

@crm_endpoint(["POST"], scope="project", permissions={"POST": "leads.import"})
def import_leads_csv(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    _require_lead_management(access, permission="leads.import", project=project)
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"file": ["Upload a file using the 'file' field."]}, status=status.HTTP_400_BAD_REQUEST)
    if upload.size > 5 * 1024 * 1024:
        return Response({"file": ["The file must not exceed 5 MB."]}, status=status.HTTP_400_BAD_REQUEST)
    if not str(upload.name).lower().endswith((".csv", ".xlsx", ".xls")):
        return Response({"file": ["Only .csv, .xlsx and .xls files are supported."]}, status=status.HTTP_400_BAD_REQUEST)
    import_duplicates = str(request.data.get("import_duplicates", "false")).lower() in {"1", "true", "yes", "on"}
    with transaction.atomic():
        batch = LeadImportBatch.objects.create(
            organization=access.organization,
            project=project,
            file_name=upload.name,
            upload=upload,
            import_duplicates=import_duplicates,
            created_by=request.user,
        )
        from .tasks import process_lead_import
        result = process_lead_import.enqueue(batch.id)
        batch.task_id = result.id
        batch.save(update_fields=["task_id", "updated_at"])
    return Response({"batch_id": batch.id, "status": batch.status}, status=status.HTTP_202_ACCEPTED)


def _import_batch_access(request, organization_slug, batch_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    batch = get_object_or_404(LeadImportBatch, pk=batch_id, organization=access.organization, project=project)
    allowed = batch.created_by_id == request.user.id or has_permission(request.user, access.organization, "leads.import", project=project)
    if not allowed:
        raise PermissionDenied("Permission denied for leads.import.")
    return access, project, batch


@crm_endpoint(["GET"], scope="project", permissions={"GET": "leads.import"})
def import_batch_progress(request, organization_slug, batch_id):
    _, _, batch = _import_batch_access(request, organization_slug, batch_id)
    return Response({
        "id": batch.id,
        "status": batch.status,
        "file_name": batch.file_name,
        "total_rows": batch.total_rows,
        "imported_rows": batch.imported_rows,
        "skipped_rows": batch.skipped_rows,
        "current_chunk": batch.current_chunk,
    })


@crm_endpoint(["GET"], scope="project", permissions={"GET": "leads.import"})
def import_batch_error_report(request, organization_slug, batch_id):
    _, _, batch = _import_batch_access(request, organization_slug, batch_id)
    if not batch.error_report:
        return Response({"detail": "Error report is not available."}, status=status.HTTP_404_NOT_FOUND)
    response = FileResponse(batch.error_report.storage.open(batch.error_report.name, "rb"), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{batch.file_name.rsplit(".", 1)[0]}-errors.csv"'
    return response


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lead_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "POST":
        _require_lead_management(access, permission="leads.add", project=project)
        try:
            lead = Lead(project=project)
            lead = _apply_payload(lead, request.data, access.organization)
            with transaction.atomic():
                lead.save()
        except (ValidationError, ValueError, TypeError) as error:
            return _validation_response(error)
        if lead.assigned_membership_id:
            _create_pending_follow_up(lead, lead.assigned_membership)
        return Response(lead_to_dict(lead), status=status.HTTP_201_CREATED)

    leads = _leads_for_access(access, project)
    leads = leads.order_by("-created_at", "-id")
    latest_follow_up = FollowUpCall.objects.filter(lead=OuterRef("pk")).order_by("-created_at")
    # Add latest follow-up status to every lead
    leads = leads.annotate(
        latest_follow_up_status=Subquery(
            latest_follow_up.values("status")[:1]
        ),
        latest_follow_up_id=Subquery(
            latest_follow_up.values("id")[:1]
        )
    )
    if status_filter := request.query_params.get("status"):
        try:
            leads = leads.filter(lifecycle_status=_canonical_lead_status(status_filter))
        except ValidationError as error:
            return _validation_response(error)
    if source := request.query_params.get("source"):
        leads = leads.filter(source=source)
    if search := request.query_params.get("search"):
        leads = leads.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )
    if owner := request.query_params.get("owner"):
        if owner.lower() in {"unassigned", "none"}:
            leads = leads.filter(assigned_membership__isnull=True)
        else:
            leads = leads.filter(assigned_membership_id=owner)
    if city := request.query_params.get("city"):
        leads = leads.filter(preferred_location__icontains=city)
    if tag := request.query_params.get("tag"):
        leads = leads.filter(tags__tag_name__iexact=tag)
    try:
        if request.query_params.get("min_score"):
            leads = leads.filter(score__gte=int(request.query_params["min_score"]))
        if request.query_params.get("max_score"):
            leads = leads.filter(score__lte=int(request.query_params["max_score"]))
    except (TypeError, ValueError):
        return Response({"score": ["Score filters must be integers."]}, status=status.HTTP_400_BAD_REQUEST)
    if date_from := request.query_params.get("date_from"):
        parsed_date = parse_date(date_from)
        if parsed_date is None:
            return Response({"date_from": ["Use YYYY-MM-DD."]}, status=status.HTTP_400_BAD_REQUEST)
        leads = leads.filter(created_at__date__gte=parsed_date)
    if date_to := request.query_params.get("date_to"):
        parsed_date = parse_date(date_to)
        if parsed_date is None:
            return Response({"date_to": ["Use YYYY-MM-DD."]}, status=status.HTTP_400_BAD_REQUEST)
        leads = leads.filter(created_at__date__lte=parsed_date)
    ordering = request.query_params.get("ordering", "-created_at")
    ordering_map = {"score": "score", "-score": "-score", "date": "created_at", "-date": "-created_at", "name": "first_name", "-name": "-first_name"}
    leads = leads.order_by(ordering_map.get(ordering, "-created_at"), "-id").distinct()
    total_count = leads.count()
    try:
        page_size = max(1, min(100, int(request.query_params.get("page_size", 50))))
        page_number = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        return Response({"page": ["Page and page_size must be integers."]}, status=status.HTTP_400_BAD_REQUEST)
    leads = leads[(page_number - 1) * page_size: page_number * page_size]
    return Response({
        "count": total_count,
        "page": page_number,
        "page_size": page_size,
        "total_pages": max(1, (total_count + page_size - 1) // page_size),
        "results": [
            lead_to_dict(
                lead,
                latest_follow_up_status=lead.latest_follow_up_status
            )
            for lead in leads
        ]
    })


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def lead_detail(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)

    if request.method == "GET":
        return Response(lead_to_dict(lead, include_follow_ups=True))

    if request.method == "DELETE":
        _require_lead_management(access)
        try:
            delete_leads_with_history(
                leads=[lead],
                request=request,
                organization=access.organization,
                project=project,
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH / PUT
    if access.can_manage_leads:
        # Admin / Manager / Platform
        pass
    else:
        # Telecaller can edit only their assigned leads
        if (
            access.membership is None
            or not has_permission(request.user, access.organization, "leads.edit")
            or lead.assigned_membership != access.membership
        ):
            raise PermissionDenied(
                "You can only edit your assigned leads."
            )

    if any(field in request.data for field in {"assigned_membership", "assigned_membership_id", "assignee_id"}):
        return Response({"detail": "Use the assign action; a reason is required."}, status=status.HTTP_400_BAD_REQUEST)

    if lead.lifecycle_status == "converted" and any(field in request.data for field in CONVERTED_LEAD_IMMUTABLE_FIELDS):
        return Response({"detail": "Converted lead identity and deal fields are immutable."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        previous_assignee_id = lead.assigned_membership_id

        with transaction.atomic():
            lead = _apply_payload(
                lead,
                request.data,
                access.organization,
                partial=request.method == "PATCH",
            )

    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)

    if (
        lead.assigned_membership_id
        and lead.assigned_membership_id != previous_assignee_id
    ):
        _create_pending_follow_up(lead, lead.assigned_membership)

    return Response(lead_to_dict(lead))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def follow_up_list(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    if request.method == "GET":
        calls = lead.follow_up_calls.select_related("telecaller_membership__user").order_by("-called_at", "-id")
        if status_filter := request.query_params.get("status"):
            calls = calls.filter(status=status_filter)
        return Response({"count": calls.count(), "results": [follow_up_to_dict(call) for call in calls]})
    if access.membership is None:
        raise PermissionDenied("A membership in this organization is required to log a follow-up call.")
    note = request.data.get("note", "").strip()
    if not note:
        return Response({"note": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        result = {"note": note, "outcome": request.data.get("outcome", FollowUpCall.Outcome.CONNECTED), "status": request.data.get("status", FollowUpCall.Status.NEW), "next_follow_up": request.data.get("next_follow_up"), "called_at": request.data.get("called_at")}
        call = FollowUpCall.objects.filter(organization=access.organization, lead=lead, telecaller_membership=access.membership, called_at__isnull=True).order_by("created_at", "id").first()
        if call:
            _update_follow_up_result(call, result)
            response_status = status.HTTP_200_OK
        else:
            call = FollowUpCall(organization=access.organization, lead=lead, telecaller_membership=access.membership)
            _update_follow_up_result(call, result)
            response_status = status.HTTP_201_CREATED
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(follow_up_to_dict(call), status=response_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_summary(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    follow_ups = FollowUpCall.objects.filter(organization=access.organization, lead__in=leads)
    statuses = {item["status"]: item["count"] for item in follow_ups.values("status").annotate(count=Count("id"))}
    return Response({"total": leads.count(), "by_status": statuses})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_dashboard(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    follow_ups = FollowUpCall.objects.filter(organization=access.organization, lead__in=leads)
    statuses = {item["status"]: item["count"] for item in follow_ups.values("status").annotate(count=Count("id"))}
    sources = {item["source"]: item["count"] for item in leads.values("source").annotate(count=Count("id"))}
    calls = follow_ups.select_related("lead", "telecaller_membership__user")[:20]
    return Response({"organization": access.organization.slug, "total_leads": leads.count(), "by_status": statuses, "by_source": sources, "recent_follow_up_calls": [follow_up_to_dict(call) for call in calls]})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_leads_round_robin_view(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    _require_lead_management(access)
    lead_ids = request.data.get("lead_ids")
    if lead_ids is not None and (not isinstance(lead_ids, list) or not all(isinstance(item, int) for item in lead_ids)):
        return Response({"lead_ids": ["Provide a list of integer lead IDs."]}, status=status.HTTP_400_BAD_REQUEST)
    leads = assign_leads_round_robin(access.organization.id, lead_ids)
    return Response({"assigned": len(leads), "results": [lead_to_dict(lead) for lead in leads]})

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sitevisit_dashboard(request, organization_slug):
    """List or schedule visits. Dates are kept as database fields for calendar queries."""
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    leads = _leads_for_access(access, project)
    if request.method == "GET":
        try:
            site_visits = _filter_site_visits(_site_visits_for_access(access, project=project), request.query_params)
        except ValidationError as exc:
            return _validation_response(exc)
        try:
            max_days_ahead = int(get_system_parameter(
                access.organization, "site_visit_max_days_ahead", project=project
            ))
        except UnknownSystemParameter:
            max_days_ahead = 90
        return Response({
            "organization": access.organization.slug,
            "count": site_visits.count(),
            "max_days_ahead": max_days_ahead,
            "results": [site_visit_to_dict(sitevisit) for sitevisit in site_visits],
        })
    lead_id = request.data.get("lead")
    if not lead_id:
        return Response({"lead": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        lead = leads.get(pk=lead_id)
    except (Lead.DoesNotExist, ValueError, TypeError):
        return Response({"error": "Lead not found or you don't have access to this lead."}, status=status.HTTP_404_NOT_FOUND)
    if not access.organization.is_active or lead.lifecycle_status in {"converted", "lost"}:
        return Response({"lead": "Only active, valid leads can be scheduled for a site visit."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        visit_date = _parse_date(request.data.get("visit_date"), "visit_date")
        visit_time = _parse_time(request.data.get("visit_time"), "visit_time")
        _schedule_validation(visit_date, visit_time, access.organization, project)
        executive = _active_executive_membership(access.organization, request.data.get("executive"))
        if not str(request.data.get("site", "")).strip():
            raise ValidationError({"site": "This field is required."})
        duration = int(request.data.get("duration_minutes") or 60)
        if duration <= 0:
            raise ValidationError({"duration_minutes": "Duration must be greater than zero."})
        with transaction.atomic():
            executive = OrganizationMembership.objects.select_for_update().get(
                pk=executive.pk, organization=access.organization, is_active=True
            )
            _ensure_executive_is_available(executive, visit_date, visit_time, duration)
            site_visit = Sitevisit(
                organization=access.organization, project=project, lead=lead, executive_membership=executive,
                visit_date=visit_date, visit_time=visit_time, duration_minutes=duration,
                site=request.data.get("site"), location=request.data.get("location"),
                customer_preference=request.data.get("customer_preference"), notes=request.data.get("notes"),
                created_by=request.user, status=Sitevisit.Status.UPCOMING,
            )
            site_visit.full_clean()
            site_visit.save()
            _record_lead_status_transition(
                lead=lead,
                status_value="site_visit_scheduled",
                user=request.user,
                reason="Automatic site-visit scheduling",
                system=True,
            )
    except OperationalError:
        return Response({"detail": "The database is busy; please retry."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except (ValidationError, ValueError, TypeError) as exc:
        return _validation_response(exc)
    return Response(site_visit_to_dict(site_visit), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def rescheduledSitevisit(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)

    if request.method == "GET":
        rescheduled_sitevisits = SitevisitReschedule.objects.select_related(
            "site_visit__lead",
            "site_visit__executive_membership__user",
            "site_visit__created_by",
        ).filter(
            site_visit__organization=access.organization,
            site_visit__project=project,
            site_visit__in=_site_visits_for_access(access, project=project),
        )
        return Response({
            "organization": access.organization.slug,
            "total_rescheduled_site_visits": rescheduled_sitevisits.count(),
            "rescheduled_site_visits": [
                reschedule_sitevisit_to_dict(rescheduled_sitevisit)
                for rescheduled_sitevisit in rescheduled_sitevisits
            ],
        })

    site_visit_id = request.data.get("site_visit")
    if not site_visit_id:
        return Response({"site_visit": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        new_date = _parse_date(request.data.get("new_date"), "new_date")
        new_time = _parse_time(request.data.get("new_time"), "new_time")
        _schedule_validation(new_date, new_time, access.organization, project)
    except ValidationError as exc:
        return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
    missing = {
        field: "This field is required."
        for field, value in {"new_date": new_date, "new_time": new_time}.items()
        if value is None
    }
    if missing:
        return Response(missing, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        try:
            site_visit = _site_visits_for_access(access, project=project).select_for_update().get(id=site_visit_id)
        except Sitevisit.DoesNotExist:
            return Response(
                {"error": "Site visit not found or you don't have access to it."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            executive = OrganizationMembership.objects.select_for_update().get(
                pk=site_visit.executive_membership_id,
                organization=access.organization,
                is_active=True,
            )
            _ensure_executive_is_available(
                executive,
                new_date,
                new_time,
                site_visit.duration_minutes or 60,
                exclude_id=site_visit.pk,
            )
            rescheduled_sitevisit = _reschedule_site_visit(
                site_visit, new_date, new_time, request.data.get("reason")
            )
        except ValidationError as exc:
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)

    return Response(reschedule_sitevisit_to_dict(rescheduled_sitevisit), status=status.HTTP_201_CREATED)


def _filter_site_visits(queryset, params):
    if value := params.get("date"):
        queryset = queryset.filter(visit_date=_parse_date(value, "date"))
    start_date = _parse_date(params.get("start_date"), "start_date")
    end_date = _parse_date(params.get("end_date"), "end_date")
    if start_date:
        queryset = queryset.filter(visit_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(visit_date__lte=end_date)
    if start_date and end_date and start_date > end_date:
        raise ValidationError({"end_date": "End date must be on or after start date."})
    if month := params.get("month"):
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            queryset = queryset.filter(visit_date__year=year, visit_date__month=month_number)
        except (TypeError, ValueError):
            raise ValidationError({"month": "Use YYYY-MM."})
    if value := params.get("status"):
        statuses = [item.strip() for item in value.split(",") if item.strip()]
        invalid = set(statuses) - set(Sitevisit.Status.values)
        if invalid:
            raise ValidationError({"status": "Use a valid site visit status."})
        queryset = queryset.filter(status__in=statuses)
    if value := params.get("lead"):
        queryset = queryset.filter(lead_id=value)
    if value := params.get("executive"):
        queryset = queryset.filter(executive_membership_id=value)
    if value := params.get("site"):
        queryset = queryset.filter(site__icontains=value)
    return queryset.order_by("visit_date", "visit_time", "id")


def _get_site_visit_or_404(access, leads, site_visit_id, for_update=False, project=None):
    queryset = _site_visits_for_access(access, leads, project=project)
    if for_update:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=site_visit_id)


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAuthenticated])
def sitevisit_detail(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if request.method == "GET":
        visit = _get_site_visit_or_404(access, None, site_visit_id, project=project)
        return Response(site_visit_to_dict(visit, include_history=True))

    with transaction.atomic():
        visit = _get_site_visit_or_404(access, None, site_visit_id, for_update=True, project=project)
        payload = request.data
        allowed = {"visit_date", "visit_time", "duration_minutes", "executive", "site", "location", "customer_preference", "notes", "status", "reschedule_reason"}
        unknown = set(payload) - allowed
        if unknown:
            return Response({field: "This field cannot be updated." for field in unknown}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target_executive = visit.executive_membership
            if "executive" in payload:
                if not access.is_platform and (not access.membership or access.membership.role not in {"manager", "admin"}):
                    raise PermissionDenied("Only managers and admins may reassign site visits.")
                target_executive = _active_executive_membership(access.organization, payload["executive"])
            if any(field in payload for field in {"visit_date", "visit_time", "executive", "duration_minutes"}):
                new_date = _parse_date(payload.get("visit_date", visit.visit_date.isoformat() if visit.visit_date else None), "visit_date")
                new_time = _parse_time(payload.get("visit_time", visit.visit_time.isoformat() if visit.visit_time else None), "visit_time")
                duration = int(payload.get("duration_minutes", visit.duration_minutes or 60) or 60)
                target_executive = OrganizationMembership.objects.select_for_update().get(
                    pk=target_executive.pk, organization=access.organization, is_active=True
                )
                _ensure_executive_is_available(target_executive, new_date, new_time, duration, exclude_id=visit.pk)
                if "executive" in payload:
                    visit.executive_membership = target_executive
            if "visit_date" in payload or "visit_time" in payload:
                new_date = _parse_date(payload.get("visit_date", visit.visit_date.isoformat() if visit.visit_date else None), "visit_date")
                new_time = _parse_time(payload.get("visit_time", visit.visit_time.isoformat() if visit.visit_time else None), "visit_time")
                _reschedule_site_visit(visit, new_date, new_time, payload.get("reschedule_reason"))
            if "duration_minutes" in payload:
                visit.duration_minutes = int(payload["duration_minutes"]) if payload["duration_minutes"] is not None else None
            for field in {"site", "location", "customer_preference", "notes"} & payload.keys():
                setattr(visit, field, payload[field])
            if "status" in payload:
                visit.transition_to(payload["status"])
            visit.full_clean()
            visit.save()
        except (ValidationError, ValueError, TypeError) as exc:
            return _validation_response(exc)
    return Response(site_visit_to_dict(visit))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sitevisit_reschedule(request, organization_slug, site_visit_id):
    """Resource-oriented reschedule endpoint; the legacy collection endpoint remains supported."""
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    try:
        new_date = _parse_date(request.data.get("new_date"), "new_date")
        new_time = _parse_time(request.data.get("new_time"), "new_time")
        _schedule_validation(new_date, new_time, access.organization, project)
    except ValidationError as exc:
        return _validation_response(exc)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, None, site_visit_id, for_update=True, project=project)
        try:
            executive = OrganizationMembership.objects.select_for_update().get(
                pk=visit.executive_membership_id,
                organization=access.organization,
                is_active=True,
            )
            _ensure_executive_is_available(
                executive, new_date, new_time, visit.duration_minutes or 60, exclude_id=visit.pk
            )
            history = _reschedule_site_visit(visit, new_date, new_time, request.data.get("reason"))
        except ValidationError as exc:
            return _validation_response(exc)
    return Response(reschedule_sitevisit_to_dict(history), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sitevisit_cancel(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    reason = str(request.data.get("cancellation_reason", "")).strip()
    if not reason:
        return Response({"cancellation_reason": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, None, site_visit_id, for_update=True, project=project)
        try:
            visit.transition_to(Sitevisit.Status.CANCELLED)
            visit.cancellation_reason = reason
            visit.cancellation_notes = request.data.get("notes")
            visit.full_clean()
            visit.save(update_fields=["status", "cancellation_reason", "cancellation_notes", "updated_at"])
        except ValidationError as exc:
            return _validation_response(exc)
    data = site_visit_to_dict(visit)
    data["notify_customer_requested"] = bool(request.data.get("notify_customer", False))
    data["notification_sent"] = False
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sitevisit_no_show(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    try:
        after_minutes = int(request.data.get("after_minutes", 15))
        if not 0 <= after_minutes <= 1440:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"after_minutes": "Use a whole number from 0 to 1440."}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, None, site_visit_id, for_update=True, project=project)
        if not visit.visit_date or not visit.visit_time:
            return Response({"visit_date": "The visit must have a date and time."}, status=status.HTTP_400_BAD_REQUEST)
        visit_at = timezone.make_aware(datetime.combine(visit.visit_date, visit.visit_time), timezone.get_current_timezone())
        if timezone.now() < visit_at + timedelta(minutes=after_minutes):
            return Response({"status": "This visit is not yet eligible to be marked as no show."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            visit.transition_to(Sitevisit.Status.NO_SHOW)
            visit.full_clean()
            visit.save(update_fields=["status", "updated_at"])
        except ValidationError as exc:
            return _validation_response(exc)
    data = site_visit_to_dict(visit)
    data["notify_executive_requested"] = bool(request.data.get("notify_executive", False))
    data["notification_sent"] = False
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sitevisit_outcome(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    outcome = request.data.get("outcome")
    if outcome not in Sitevisit.Outcome.values:
        return Response({"outcome": "Use a valid outcome."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        interest_level = int(request.data.get("interest_level"))
    except (TypeError, ValueError):
        return Response({"interest_level": "Use an integer from 1 to 5."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            visit = _get_site_visit_or_404(access, None, site_visit_id, for_update=True, project=project)
            visit.transition_to(Sitevisit.Status.COMPLETED)
            visit.outcome = outcome
            visit.interest_level = interest_level
            visit.remarks = request.data.get("remarks")
            visit.full_clean()
            visit.save(update_fields=["status", "outcome", "interest_level", "remarks", "updated_at"])
            _record_lead_status_transition(
                lead=visit.lead,
                status_value="site_visit_completed",
                user=request.user,
                reason="Automatic site-visit completion",
                system=True,
            )
            lead = Lead.objects.select_for_update().get(pk=visit.lead_id)
            lead.score = (lead.score or 0) + 20
            lead.save(update_fields=["score", "updated_at"])
    except ValidationError as exc:
        return _validation_response(exc)
    return Response(site_visit_to_dict(visit))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_history(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    visit = _get_site_visit_or_404(access, None, site_visit_id, project=project)
    return Response(site_visit_to_dict(visit, include_history=True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_sitevisits(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    lead = get_object_or_404(_leads_for_access(access, project), pk=lead_id)
    visits = _site_visits_for_access(access, _leads_for_access(access, project), project).filter(lead=lead).order_by("-visit_date", "-visit_time", "-id")
    return Response({"lead": lead_to_dict(lead), "count": visits.count(), "results": [site_visit_to_dict(visit) for visit in visits]})


def _paginate(queryset, params):
    try:
        page = max(int(params.get("page", 1)), 1)
        page_size = min(max(int(params.get("page_size", 25)), 1), 100)
    except ValueError:
        raise ValidationError({"page": "Page and page_size must be integers."})
    count = queryset.count()
    start = (page - 1) * page_size
    return count, page, page_size, queryset[start:start + page_size]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_upcoming(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    visits = _site_visits_for_access(access, project=project).filter(
        visit_date__gte=timezone.localdate(),
        status__in=[Sitevisit.Status.SCHEDULED, Sitevisit.Status.UPCOMING, Sitevisit.Status.RESCHEDULED],
    ).order_by("visit_date", "visit_time", "id")
    try:
        count, page, page_size, results = _paginate(visits, request.query_params)
    except ValidationError as exc:
        return _validation_response(exc)
    base = request.build_absolute_uri(request.path)
    next_url = f"{base}?page={page + 1}&page_size={page_size}" if page * page_size < count else None
    previous_url = f"{base}?page={page - 1}&page_size={page_size}" if page > 1 else None
    return Response({"count": count, "next": next_url, "previous": previous_url, "results": [site_visit_to_dict(visit) for visit in results]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_today(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    visits = _site_visits_for_access(access, project=project).filter(visit_date=timezone.localdate())
    if executive := request.query_params.get("executive"):
        visits = visits.filter(executive_membership_id=executive)
    return Response({"date": timezone.localdate().isoformat(), "count": visits.count(), "results": [site_visit_to_dict(visit) for visit in visits.order_by("visit_time", "id")]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_calendar(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    try:
        visits = _filter_site_visits(_site_visits_for_access(access, project=project), request.query_params)
        if not request.query_params.get("start_date") and not request.query_params.get("month"):
            raise ValidationError({"start_date": "Provide start_date/end_date or month for calendar data."})
    except ValidationError as exc:
        return _validation_response(exc)
    events = []
    for visit in visits:
        start = None
        if visit.visit_date and visit.visit_time:
            start = timezone.make_aware(datetime.combine(visit.visit_date, visit.visit_time), timezone.get_current_timezone()).isoformat()
        events.append({"id": visit.id, "title": visit.lead.full_name, "start": start, "status": visit.status, "site": visit.site, "location": visit.location})
    return Response({"count": len(events), "results": events})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_analytics(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    try:
        visits = _filter_site_visits(_site_visits_for_access(access, project=project), request.query_params)
    except ValidationError as exc:
        return _validation_response(exc)
    summary = visits.aggregate(total_visits=Count("id"), average_interest_level=Avg("interest_level"))
    by_status = {row["status"]: row["count"] for row in visits.values("status").annotate(count=Count("id"))}
    outcomes = {row["outcome"]: row["count"] for row in visits.exclude(outcome__isnull=True).values("outcome").annotate(count=Count("id"))}
    trend = [{"date": row["visit_date"].isoformat(), "count": row["count"]} for row in visits.exclude(visit_date__isnull=True).values("visit_date").annotate(count=Count("id")).order_by("visit_date")]
    return Response({"total_visits": summary["total_visits"], "completed": by_status.get(Sitevisit.Status.COMPLETED, 0), "no_show": by_status.get(Sitevisit.Status.NO_SHOW, 0), "cancelled": by_status.get(Sitevisit.Status.CANCELLED, 0), "average_interest_level": summary["average_interest_level"], "outcome_distribution": outcomes, "visits_trend": trend})
