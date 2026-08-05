import pandas as pd
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, OuterRef , Subquery
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.models import OrganizationMembership
from organizations.services import get_organization_access
from .models import FollowUpCall, Lead
from .serializers import follow_up_to_dict, lead_to_dict
from .services import assign_leads_round_robin


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

def _leads_for_access(access):
    leads = Lead.objects.filter(organization=access.organization).select_related("organization", "assigned_membership__user")
    return leads if access.can_view_all_leads else leads.filter(assigned_membership=access.membership)


def _require_lead_management(access):
    if not access.can_manage_leads:
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can manage leads.")


def _apply_payload(lead, payload, organization, partial=False, save=True):
    allowed = {"first_name", "last_name", "email", "phone", "source", "assigned_membership"}
    if not partial:
        missing = [field for field in ("first_name", "phone", "source") if field not in payload]
        if missing:
            raise ValidationError({field: "This field is required." for field in missing})
    for field in allowed & payload.keys():
        value = payload[field]
        if field == "assigned_membership":
            value = OrganizationMembership.objects.filter(pk=value, organization=organization, is_active=True).first() if value else None
            if payload[field] and value is None:
                raise ValidationError({"assigned_membership": "Use an active membership in this organization."})
            field = "assigned_membership"
        setattr(lead, field, value)
    lead.organization = organization
    lead.full_clean()
    if save:
        lead.save()
    return lead


def _validation_response(error):
    if hasattr(error, "message_dict"):
        details = error.message_dict
    elif hasattr(error, "messages"):
        details = {"detail": error.messages}
    else:
        details = {"detail": [str(error)]}
    return Response(details, status=status.HTTP_400_BAD_REQUEST)

def _create_pending_follow_up(lead, telecaller):
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
        call.next_follow_up = _parse_date(payload["next_follow_up"], "next_follow_up")
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
def assign_lead(request, organization_slug, lead_id):
    """Assign or reassign one organization lead to an active telecaller."""
    access = get_organization_access(request.user, organization_slug)
    _require_lead_management(access)
    lead = get_object_or_404(Lead.objects.filter(organization=access.organization), pk=lead_id)
    membership_id = request.data.get("telecaller_membership")
    if not membership_id:
        return Response({"telecaller_membership": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    telecaller = OrganizationMembership.objects.filter(
        pk=membership_id,
        organization=access.organization,
        role=OrganizationMembership.Role.TELECALLER,
        is_active=True,
    ).select_related("user").first()
    if telecaller is None:
        return Response({"telecaller_membership": ["Use an active telecaller membership in this organization."]}, status=status.HTTP_400_BAD_REQUEST)
    lead.assigned_membership = telecaller
    lead.full_clean()
    lead.save(update_fields=["assigned_membership", "updated_at"])
    _create_pending_follow_up(lead, telecaller)
    return Response(lead_to_dict(lead))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def assigned_leads(request, organization_slug):
    """Return leads assigned to the authenticated organization member."""
    access = get_organization_access(request.user, organization_slug)
    if access.membership is None or access.membership.role != OrganizationMembership.Role.TELECALLER:
        raise PermissionDenied("Only telecallers can view their assigned leads.")
    leads = Lead.objects.filter(
        organization=access.organization,
        assigned_membership=access.membership,
    ).select_related("organization", "assigned_membership__user")
    return Response({"count": leads.count(), "results": [lead_to_dict(lead) for lead in leads]})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_leads_csv(request, organization_slug):
    """Atomically import leads from CSV/XLS/XLSX upload."""

    access = get_organization_access(request.user, organization_slug)
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
            leads.append(
                _apply_payload(
                    Lead(),
                    _csv_row_payload(row),
                    access.organization,
                    save=False,
                )
            )
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

    return Response(
        {
            "imported": len(leads),
            "results": [lead_to_dict(lead) for lead in leads],
        },
        status=status.HTTP_201_CREATED,
    )

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
        if lead.assigned_membership_id:
            _create_pending_follow_up(lead, lead.assigned_membership)
        return Response(lead_to_dict(lead), status=status.HTTP_201_CREATED)

    leads = _leads_for_access(access)
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
        leads = leads.filter(
            latest_follow_up_status=status_filter,
            latest_follow_up_id__isnull=False
        )
    if source := request.query_params.get("source"):
        leads = leads.filter(source=source)
    if search := request.query_params.get("search"):
        leads = leads.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )
    return Response({
        "count": leads.count(),
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
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    if request.method == "GET":
        return Response(lead_to_dict(lead, include_follow_ups=True))
    _require_lead_management(access)
    if request.method == "DELETE":
        lead.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        previous_assignee_id = lead.assigned_membership_id
        lead = _apply_payload(lead, request.data, access.organization, partial=request.method == "PATCH")
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    if lead.assigned_membership_id and lead.assigned_membership_id != previous_assignee_id:
        _create_pending_follow_up(lead, lead.assigned_membership)
    return Response(lead_to_dict(lead))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def follow_up_list(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    if request.method == "GET":
        calls = lead.follow_up_calls.select_related("telecaller_membership__user").all()
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
