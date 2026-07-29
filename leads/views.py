from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.models import OrganizationMembership
from organizations.services import get_organization_access
from .models import FollowUpCall, Lead
from .serializers import follow_up_to_dict, lead_to_dict


def _parse_datetime(value, field_name):
    if value is None:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError({field_name: "Use an ISO 8601 datetime."})
    return parsed


def _leads_for_access(access):
    leads = Lead.objects.filter(organization=access.organization).select_related("organization", "assigned_membership__user")
    return leads if access.can_view_all_leads else leads.filter(assigned_membership=access.membership)


def _require_lead_management(access):
    if not access.can_manage_leads:
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can manage leads.")


def _apply_payload(lead, payload, organization, partial=False):
    allowed = {"first_name", "last_name", "email", "phone", "source", "status", "next_follow_up", "assigned_membership"}
    if not partial:
        missing = [field for field in ("first_name", "phone", "source") if field not in payload]
        if missing:
            raise ValidationError({field: "This field is required." for field in missing})
    for field in allowed & payload.keys():
        value = payload[field]
        if field == "next_follow_up":
            value = _parse_datetime(value, field)
        if field == "assigned_membership":
            value = OrganizationMembership.objects.filter(pk=value, organization=organization, is_active=True).first() if value else None
            if payload[field] and value is None:
                raise ValidationError({"assigned_membership": "Use an active membership in this organization."})
            field = "assigned_membership"
        setattr(lead, field, value)
    lead.organization = organization
    lead.full_clean()
    lead.save()
    return lead


def _validation_response(error):
    details = error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}
    return Response(details, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lead_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "POST":
        _require_lead_management(access)
        try:
            lead = _apply_payload(Lead(), request.data, access.organization)
        except (ValidationError, ValueError, TypeError) as error:
            return _validation_response(error)
        return Response(lead_to_dict(lead), status=status.HTTP_201_CREATED)

    leads = _leads_for_access(access)
    if status_filter := request.query_params.get("status"):
        leads = leads.filter(status=status_filter)
    if source := request.query_params.get("source"):
        leads = leads.filter(source=source)
    if search := request.query_params.get("search"):
        leads = leads.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search) | Q(phone__icontains=search))
    return Response({"count": leads.count(), "results": [lead_to_dict(lead) for lead in leads]})


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def lead_detail(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    if request.method == "GET":
        return Response(lead_to_dict(lead, include_follow_ups=True))
    _require_lead_management(access)
    if request.method == "DELETE":
        lead.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        lead = _apply_payload(lead, request.data, access.organization, partial=request.method == "PATCH")
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(lead_to_dict(lead))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def follow_up_list(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    if request.method == "GET":
        calls = lead.follow_up_calls.select_related("telecaller_membership__user").all()
        return Response({"count": calls.count(), "results": [follow_up_to_dict(call) for call in calls]})
    if access.membership is None:
        raise PermissionDenied("A membership in this organization is required to log a follow-up call.")
    note = request.data.get("note", "").strip()
    if not note:
        return Response({"note": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        called_at = _parse_datetime(request.data.get("called_at"), "called_at") if request.data.get("called_at") else None
        call = FollowUpCall(organization=access.organization, lead=lead, telecaller_membership=access.membership, note=note, outcome=request.data.get("outcome", FollowUpCall.Outcome.CONNECTED), **({"called_at": called_at} if called_at else {}))
        call.full_clean()
        call.save()
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(follow_up_to_dict(call), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_summary(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    statuses = {item["status"]: item["count"] for item in leads.values("status").annotate(count=Count("id"))}
    return Response({"total": leads.count(), "by_status": statuses})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_dashboard(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    statuses = {item["status"]: item["count"] for item in leads.values("status").annotate(count=Count("id"))}
    sources = {item["source"]: item["count"] for item in leads.values("source").annotate(count=Count("id"))}
    calls = FollowUpCall.objects.filter(organization=access.organization, lead__in=leads).select_related("lead", "telecaller_membership__user")[:20]
    return Response({"organization": access.organization.slug, "total_leads": leads.count(), "by_status": statuses, "by_source": sources, "recent_follow_up_calls": [follow_up_to_dict(call) for call in calls]})