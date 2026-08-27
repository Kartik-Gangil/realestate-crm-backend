import pandas as pd
import io
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.models import OrganizationMembership
from organizations.services import get_organization_access, has_permission
from .models import FollowUpCall, Lead , Sitevisit , SitevisitReschedule
from .serializers import (
    follow_up_to_dict,
    lead_to_dict,
    reschedule_sitevisit_to_dict,
    site_visit_to_dict,
)
from .services import assign_leads_round_robin
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


def _site_visits_for_access(access, leads):
    return Sitevisit.objects.filter(
        organization=access.organization,
        lead__in=leads,
    ).select_related(
        "organization", "lead", "executive_membership__user", "created_by"
    ).prefetch_related("reschedules")


def _schedule_validation(visit_date, visit_time):
    errors = {}
    if visit_date is None:
        errors["visit_date"] = "This field is required."
    if visit_time is None:
        errors["visit_time"] = "This field is required."
    if visit_date:
        today = timezone.localdate()
        if visit_date < today:
            errors["visit_date"] = "A site visit cannot be scheduled in the past."
        elif visit_date > today + timedelta(days=90):
            errors["visit_date"] = "A site visit cannot be scheduled more than 90 days ahead."
    if errors:
        raise ValidationError(errors)


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


def _reschedule_site_visit(site_visit, new_date, new_time, reason=None):
    if site_visit.status in {
        Sitevisit.Status.COMPLETED, Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW,
    }:
        raise ValidationError({"status": "Completed, cancelled, and no-show visits cannot be rescheduled."})
    _schedule_validation(new_date, new_time)
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

def _leads_for_access(access):
    leads = Lead.objects.filter(organization=access.organization).select_related("organization", "assigned_membership__user")
    return leads if access.can_view_all_leads else leads.filter(assigned_membership=access.membership)


def _require_lead_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "leads.edit"):
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can manage leads.")


def _apply_payload(lead, payload, organization, partial=False, save=True):
    allowed = {"first_name", "last_name", "email", "phone", "source", "assigned_membership" , "alt_phone", "address" , "occupation"}
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
    _require_lead_management(access)

    leads = Lead.objects.filter(
        organization=access.organization,
        assigned_membership__isnull=False,
    )

    updated_count = leads.update(
        assigned_membership=None,
        updated_at=timezone.now(),
    )

    return Response({
        "message": "Lead assignments reset successfully.",
        "updated_count": updated_count,
    }, status=status.HTTP_200_OK)



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

    if request.method == "DELETE":
        _require_lead_management(access)
        lead.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH / PUT
    if access.can_manage_leads:
        # Admin / Manager / Platform
        pass
    else:
        # Telecaller can edit only their assigned leads
        if (
            access.membership is None
            or access.membership.role != OrganizationMembership.Role.TELECALLER
            or lead.assigned_membership != access.membership
        ):
            raise PermissionDenied(
                "You can only edit your assigned leads."
            )

    try:
        previous_assignee_id = lead.assigned_membership_id

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

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sitevisit_dashboard(request, organization_slug):
    """List or schedule visits. Dates are kept as database fields for calendar queries."""
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    if request.method == "GET":
        try:
            site_visits = _filter_site_visits(_site_visits_for_access(access, leads), request.query_params)
        except ValidationError as exc:
            return _validation_response(exc)
        return Response({
            "organization": access.organization.slug,
            "count": site_visits.count(),
            "results": [site_visit_to_dict(sitevisit) for sitevisit in site_visits],
        })
    lead_id = request.data.get("lead")
    if not lead_id:
        return Response({"lead": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        lead = leads.get(pk=lead_id)
    except (Lead.DoesNotExist, ValueError, TypeError):
        return Response({"error": "Lead not found or you don't have access to this lead."}, status=status.HTTP_404_NOT_FOUND)
    try:
        visit_date = _parse_date(request.data.get("visit_date"), "visit_date")
        visit_time = _parse_time(request.data.get("visit_time"), "visit_time")
        _schedule_validation(visit_date, visit_time)
        executive = _active_executive(access.organization, request.user)
        if not str(request.data.get("site", "")).strip():
            raise ValidationError({"site": "This field is required."})
        # if request.data.get("duration_minutes") is None:
        #     raise ValidationError({"duration_minutes": "This field is required."})
        # duration = int(request.data["duration_minutes"])
        with transaction.atomic():
            site_visit = Sitevisit(
                organization=access.organization, lead=lead, executive_membership=executive,
                visit_date=visit_date, visit_time=visit_time, duration_minutes=1,
                site=request.data.get("site"), location=request.data.get("location"),
                customer_preference=request.data.get("customer_preference"), notes=request.data.get("notes"),
                created_by=request.user, status=Sitevisit.Status.UPCOMING,
            )
            site_visit.full_clean()
            site_visit.save()
    except (ValidationError, ValueError, TypeError) as exc:
        return _validation_response(exc)
    return Response(site_visit_to_dict(site_visit), status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def rescheduledSitevisit(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)

    if request.method == "GET":
        rescheduled_sitevisits = SitevisitReschedule.objects.select_related(
            "site_visit__lead",
            "site_visit__executive_membership__user",
            "site_visit__created_by",
        ).filter(
            site_visit__organization=access.organization,
            site_visit__lead__in=leads,
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
        _schedule_validation(new_date, new_time)
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
            site_visit = Sitevisit.objects.select_for_update().get(
                id=site_visit_id,
                organization=access.organization,
                lead__in=leads,
            )
        except Sitevisit.DoesNotExist:
            return Response(
                {"error": "Site visit not found or you don't have access to it."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
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


def _get_site_visit_or_404(access, leads, site_visit_id, for_update=False):
    queryset = _site_visits_for_access(access, leads)
    if for_update:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=site_visit_id)


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAuthenticated])
def sitevisit_detail(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    if request.method == "GET":
        visit = _get_site_visit_or_404(access, leads, site_visit_id)
        return Response(site_visit_to_dict(visit, include_history=True))

    with transaction.atomic():
        visit = _get_site_visit_or_404(access, leads, site_visit_id, for_update=True)
        payload = request.data
        allowed = {"visit_date", "visit_time", "duration_minutes", "executive", "site", "location", "customer_preference", "notes", "status", "reschedule_reason"}
        unknown = set(payload) - allowed
        if unknown:
            return Response({field: "This field cannot be updated." for field in unknown}, status=status.HTTP_400_BAD_REQUEST)
        try:
            if "visit_date" in payload or "visit_time" in payload:
                new_date = _parse_date(payload.get("visit_date", visit.visit_date.isoformat() if visit.visit_date else None), "visit_date")
                new_time = _parse_time(payload.get("visit_time", visit.visit_time.isoformat() if visit.visit_time else None), "visit_time")
                _reschedule_site_visit(visit, new_date, new_time, payload.get("reschedule_reason"))
            if "executive" in payload:
                visit.executive_membership = _active_executive(access.organization, payload["executive"])
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
    leads = _leads_for_access(access)
    try:
        new_date = _parse_date(request.data.get("new_date"), "new_date")
        new_time = _parse_time(request.data.get("new_time"), "new_time")
        _schedule_validation(new_date, new_time)
    except ValidationError as exc:
        return _validation_response(exc)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, leads, site_visit_id, for_update=True)
        try:
            history = _reschedule_site_visit(visit, new_date, new_time, request.data.get("reason"))
        except ValidationError as exc:
            return _validation_response(exc)
    return Response(reschedule_sitevisit_to_dict(history), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sitevisit_cancel(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    leads = _leads_for_access(access)
    reason = str(request.data.get("cancellation_reason", "")).strip()
    if not reason:
        return Response({"cancellation_reason": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, leads, site_visit_id, for_update=True)
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
    leads = _leads_for_access(access)
    try:
        after_minutes = int(request.data.get("after_minutes", 15))
        if not 0 <= after_minutes <= 1440:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"after_minutes": "Use a whole number from 0 to 1440."}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, leads, site_visit_id, for_update=True)
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
    leads = _leads_for_access(access)
    outcome = request.data.get("outcome")
    if outcome not in Sitevisit.Outcome.values:
        return Response({"outcome": "Use a valid outcome."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        interest_level = int(request.data.get("interest_level"))
    except (TypeError, ValueError):
        return Response({"interest_level": "Use an integer from 1 to 5."}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        visit = _get_site_visit_or_404(access, leads, site_visit_id, for_update=True)
        try:
            visit.transition_to(Sitevisit.Status.COMPLETED)
            visit.outcome = outcome
            visit.interest_level = interest_level
            visit.remarks = request.data.get("remarks")
            visit.full_clean()
            visit.save(update_fields=["status", "outcome", "interest_level", "remarks", "updated_at"])
        except ValidationError as exc:
            return _validation_response(exc)
    return Response(site_visit_to_dict(visit))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_history(request, organization_slug, site_visit_id):
    access = get_organization_access(request.user, organization_slug)
    visit = _get_site_visit_or_404(access, _leads_for_access(access), site_visit_id)
    return Response(site_visit_to_dict(visit, include_history=True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_sitevisits(request, organization_slug, lead_id):
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    visits = _site_visits_for_access(access, _leads_for_access(access)).filter(lead=lead).order_by("-visit_date", "-visit_time", "-id")
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
    visits = _site_visits_for_access(access, _leads_for_access(access)).filter(
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
    visits = _site_visits_for_access(access, _leads_for_access(access)).filter(visit_date=timezone.localdate())
    if executive := request.query_params.get("executive"):
        visits = visits.filter(executive_membership_id=executive)
    return Response({"date": timezone.localdate().isoformat(), "count": visits.count(), "results": [site_visit_to_dict(visit) for visit in visits.order_by("visit_time", "id")]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sitevisit_calendar(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    try:
        visits = _filter_site_visits(_site_visits_for_access(access, _leads_for_access(access)), request.query_params)
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
    try:
        visits = _filter_site_visits(_site_visits_for_access(access, _leads_for_access(access)), request.query_params)
    except ValidationError as exc:
        return _validation_response(exc)
    summary = visits.aggregate(total_visits=Count("id"), average_interest_level=Avg("interest_level"))
    by_status = {row["status"]: row["count"] for row in visits.values("status").annotate(count=Count("id"))}
    outcomes = {row["outcome"]: row["count"] for row in visits.exclude(outcome__isnull=True).values("outcome").annotate(count=Count("id"))}
    trend = [{"date": row["visit_date"].isoformat(), "count": row["count"]} for row in visits.exclude(visit_date__isnull=True).values("visit_date").annotate(count=Count("id")).order_by("visit_date")]
    return Response({"total_visits": summary["total_visits"], "completed": by_status.get(Sitevisit.Status.COMPLETED, 0), "no_show": by_status.get(Sitevisit.Status.NO_SHOW, 0), "cancelled": by_status.get(Sitevisit.Status.CANCELLED, 0), "average_interest_level": summary["average_interest_level"], "outcome_distribution": outcomes, "visits_trend": trend})
