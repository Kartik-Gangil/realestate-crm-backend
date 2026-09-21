import csv
import io
import json
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Avg, Count, Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.models import OrganizationMembership
from organizations.services import get_organization_access, has_permission, membership_role_code
from system_settings.master_data import (
    active_call_dispositions,
    ensure_lead_sources,
    validate_lead_source,
    validate_site_visit_outcome,
)
from system_settings.services import get_system_parameter
from system_settings.audit import log_audit
from .models import FollowUpCall, Lead, LeadAssignmentHistory, LeadImportBatch, LeadTag, Sitevisit, SitevisitReschedule
from .duplicates import find_duplicates
from .imports import enqueue_lead_import
from .lifecycle import LEAD_STATUS_TRANSITIONS, assign_lead as assign_lead_lifecycle, transition_lead_status
from .reminders import sync_follow_up_reminder
from .serializers import (
    call_queue_item_to_dict,
    follow_up_to_dict,
    lead_to_dict,
    manual_call_log_to_dict,
    membership_to_dict,
    reschedule_sitevisit_to_dict,
    site_visit_to_dict,
)
from .services import (
    assign_leads_round_robin,
    get_call_queue,
    get_team_call_analytics,
    log_manual_call,
    redistribute_call_queue,
)
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
    visits = Sitevisit.objects.filter(
        organization=access.organization,
    ).select_related(
        "organization", "lead", "executive_membership__user", "created_by"
    ).prefetch_related("reschedules")
    role = membership_role_code(access.membership)
    if role in {"site_visit_exec", "site_visit_executive"}:
        return visits.filter(executive_membership=access.membership)
    return visits.filter(lead__in=leads)


def _max_site_visit_days(organization, project_id=None):
    value = get_system_parameter(
        organization,
        "site_visit_max_days_ahead",
        default=90,
        project=project_id,
    )
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 90
    return value if value > 0 else 90


def _schedule_validation(visit_date, visit_time, *, organization=None, project_id=None):
    errors = {}
    if visit_date is None:
        errors["visit_date"] = "This field is required."
    if visit_time is None:
        errors["visit_time"] = "This field is required."
    if visit_date:
        today = timezone.localdate()
        if visit_date < today:
            errors["visit_date"] = "A site visit cannot be scheduled in the past."
        elif organization and visit_date > today + timedelta(days=_max_site_visit_days(organization, project_id)):
            errors["visit_date"] = "A site visit cannot be scheduled beyond the configured future-day limit."
    if errors:
        raise ValidationError(errors)


def _active_executive(organization, membership_id):
    executive = OrganizationMembership.objects.filter(
        organization=organization,
        pk=membership_id,
        is_active=True
    ).select_related("user").first()

    if executive is None:
        raise ValidationError({
            "executive": "Authenticated user is not an active organization member."
        })

    return executive


def _ensure_executive_available(*, organization, executive, visit_date, visit_time, duration_minutes, ignore_visit_id=None):
    """FR-P7-01: reject overlapping active visits for the same executive."""
    start_minutes = visit_time.hour * 60 + visit_time.minute
    end_minutes = start_minutes + duration_minutes
    existing = Sitevisit.objects.select_for_update().filter(
        organization=organization,
        executive_membership=executive,
        visit_date=visit_date,
    ).exclude(status__in={Sitevisit.Status.COMPLETED, Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW})
    if ignore_visit_id is not None:
        existing = existing.exclude(pk=ignore_visit_id)
    for visit in existing:
        if not visit.visit_time:
            continue
        existing_start = visit.visit_time.hour * 60 + visit.visit_time.minute
        existing_end = existing_start + (visit.duration_minutes or 60)
        if start_minutes < existing_end and existing_start < end_minutes:
            raise ValidationError({"executive": "The executive is already booked for an overlapping visit."})


def _reschedule_site_visit(site_visit, new_date, new_time, reason=None):
    if site_visit.status in {
        Sitevisit.Status.COMPLETED, Sitevisit.Status.CANCELLED, Sitevisit.Status.NO_SHOW,
    }:
        raise ValidationError({"status": "Completed, cancelled, and no-show visits cannot be rescheduled."})
    _schedule_validation(
        new_date,
        new_time,
        organization=site_visit.organization,
        project_id=site_visit.project_id,
    )
    _ensure_executive_available(
        organization=site_visit.organization,
        executive=site_visit.executive_membership,
        visit_date=new_date,
        visit_time=new_time,
        duration_minutes=site_visit.duration_minutes or 60,
        ignore_visit_id=site_visit.id,
    )
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


def _complete_lead_for_site_visit(*, lead, actor, organization):
    """Advance a valid lead through Phase 5 before marking visit completion."""
    if lead.status == "site_visit_completed":
        return lead
    paths = {
        "new": ["contacted", "interested", "site_visit_scheduled", "site_visit_completed"],
        "contacted": ["interested", "site_visit_scheduled", "site_visit_completed"],
        "interested": ["site_visit_scheduled", "site_visit_completed"],
        "site_visit_scheduled": ["site_visit_completed"],
    }
    path = paths.get(lead.status)
    if path is None:
        raise ValidationError({"lead": "The lead is not eligible for site-visit completion."})
    for next_status in path:
        if next_status not in LEAD_STATUS_TRANSITIONS.get(lead.status, set()):
            raise ValidationError({"lead": "The lead cannot follow the required lifecycle path."})
        lead = transition_lead_status(
            lead_id=lead.id,
            new_status=next_status,
            actor=actor,
            organization=organization,
        )
    return lead

def _leads_for_access(access):
    leads = Lead.objects.filter(organization=access.organization).select_related("organization", "assigned_membership__user")
    return leads if access.can_view_all_leads else leads.filter(assigned_membership=access.membership)


def _require_lead_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "leads.edit"):
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can manage leads.")


def _require_manual_lead_creation(access):
    if access.is_platform:
        return
    if not any(has_permission(access.membership.user, access.organization, code) for code in ("leads.add", "leads.create", "leads.edit")):
        raise PermissionDenied("This role cannot create manual leads.")


def _require_ad_or_import_management(access):
    if access.is_platform:
        return
    if membership_role_code(access.membership) not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER}:
        raise PermissionDenied("Only Admins and Managers may trigger ad sync or CSV import.")


def _duplicate_response(matches):
    return [
        {
            "lead": lead_to_dict(lead),
            "confidence": confidence,
        }
        for confidence, lead in matches
    ]


def _lead_duplicate_matches(access, payload, *, project=None):
    return find_duplicates(
        organization=access.organization,
        payload=payload,
        queryset=Lead.all_objects.filter(organization=access.organization, project=project),
        project=project,
    )


def _apply_payload(lead, payload, organization, partial=False, save=True):
    allowed = {"first_name", "last_name", "email", "phone", "source", "assigned_membership", "alt_phone", "address", "city", "occupation", "score"}
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
    if "source" in payload:
        validate_lead_source(organization, lead.source)
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


@transaction.atomic
def _schedule_follow_up(call, payload):
    """API-P6-04 schedules work; API-P6-06 is the sole call-log writer."""
    allowed = {"note", "notes", "reason", "status", "next_follow_up", "follow_up_date"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError({
            field: "Call activity must be submitted through API-P6-06 /telecalling/calls/log/."
            for field in unknown
        })
    note = str(payload.get("note", payload.get("notes", payload.get("reason", ""))) or "").strip()
    if not note:
        raise ValidationError({"note": "This field is required."})
    raw_follow_up = payload.get("next_follow_up", payload.get("follow_up_date"))
    if raw_follow_up in (None, ""):
        raise ValidationError({"next_follow_up": "A follow-up date and time is required."})
    call.note = note
    if "status" in payload:
        call.status = payload["status"]
    call.next_follow_up = _parse_datetime(raw_follow_up, "next_follow_up")
    call.outcome = ""
    call.called_at = None
    call.full_clean()
    if call.pk:
        call.save(update_fields=["note", "outcome", "status", "next_follow_up", "called_at"])
    else:
        call.save()
    sync_follow_up_reminder(call)
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



@api_view(["POST", "PATCH"])
@permission_classes([IsAuthenticated])
def assign_lead(request, organization_slug, lead_id):
    """FR-P5-03/API-P5-04: assign with a mandatory reason and append history."""
    access = get_organization_access(request.user, organization_slug)
    if not access.is_platform and membership_role_code(access.membership) not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER}:
        raise PermissionDenied("Only Managers and Admins may reassign leads.")
    lead = get_object_or_404(Lead.all_objects.filter(organization=access.organization), pk=lead_id)
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
    try:
        lead = assign_lead_lifecycle(
            lead_id=lead.id, membership=telecaller, reason=request.data.get("reason"), actor=request.user, organization=access.organization
        )
    except (ValidationError, ProtectedError) as error:
        return _validation_response(error)
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
    """FR-P4-03/API-P4-04: enqueue a 5MB CSV for 500-row background processing."""
    access = get_organization_access(request.user, organization_slug)
    _require_ad_or_import_management(access)

    upload = request.FILES.get("file")
    if upload is None:
        return Response(
            {"file": ["Upload a file using the 'file' field."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if upload.size > 5 * 1024 * 1024:
        return Response({"file": ["The CSV file must not exceed 5 MB."]}, status=status.HTTP_400_BAD_REQUEST)
    if not upload.name.lower().endswith(".csv"):
        return Response({"file": ["Only .csv files are supported."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        raw_content = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw_content))
        headers = reader.fieldnames or []
    except (UnicodeDecodeError, csv.Error) as error:
        return Response({"file": [f"Could not read CSV: {error}"]}, status=status.HTTP_400_BAD_REQUEST)
    if not headers:
        return Response(
            {"file": ["The file must include a header row."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from .imports import CSV_HEADER_ALIASES, normalize_header
    mapped_headers = {CSV_HEADER_ALIASES.get(normalize_header(header)) for header in headers if header}
    if "phone" not in mapped_headers or ("first_name" not in mapped_headers and "full_name" not in mapped_headers):
        return Response(
            {"file": ["Required columns: first_name (or full_name/name) and phone."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    mapping = request.data.get("mapping", {})
    if isinstance(mapping, str):
        try:
            mapping = json.loads(mapping)
        except json.JSONDecodeError:
            return Response({"mapping": ["Mapping must be valid JSON."]}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(mapping, dict):
        return Response({"mapping": ["Mapping must be an object."]}, status=status.HTTP_400_BAD_REQUEST)
    batch = LeadImportBatch.all_objects.create(
        organization=access.organization,
        project=getattr(request, "project", None),
        file_name=upload.name,
        raw_content=raw_content,
        field_mapping=mapping,
        total_rows=max(sum(1 for _ in csv.DictReader(io.StringIO(raw_content))), 0),
        created_by=request.user,
    )
    enqueue_lead_import(batch.id)
    return Response(
        {"batch_id": batch.id, "status": batch.status, "total_rows": batch.total_rows, "imported_rows": 0, "skipped_rows": 0},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lead_import_batch_detail(request, organization_slug, batch_id):
    access = get_organization_access(request.user, organization_slug)
    batch = get_object_or_404(LeadImportBatch.all_objects, pk=batch_id, organization=access.organization)
    if request.query_params.get("download") in {"1", "true"}:
        from django.http import HttpResponse
        response = HttpResponse("row,errors\n", content_type="text/csv")
        for item in batch.error_report:
            response.write(f'{item.get("row")},"{json.dumps(item.get("errors", {})).replace(chr(34), chr(34) * 2)}"\n')
        response["Content-Disposition"] = f'attachment; filename="{batch.file_name}.errors.csv"'
        return response
    return Response({
        "id": batch.id, "file_name": batch.file_name, "status": batch.status,
        "total_rows": batch.total_rows, "imported_rows": batch.imported_rows,
        "skipped_rows": batch.skipped_rows, "error_report": batch.error_report,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def check_duplicate(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    _require_manual_lead_creation(access)
    matches = _lead_duplicate_matches(access, request.data, project=getattr(request, "project", None))
    return Response({"matches": _duplicate_response(matches)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def manual_lead(request, organization_slug):
    """FR-P4-02/05: save a manual lead only after duplicate warning/resolution."""
    access = get_organization_access(request.user, organization_slug)
    _require_manual_lead_creation(access)
    payload = request.data.copy()
    duplicate_action = payload.pop("duplicate_action", None)
    matches = _lead_duplicate_matches(access, payload, project=getattr(request, "project", None))
    if matches and duplicate_action not in {"create_anyway", "merge"}:
        return Response({"code": "duplicate_warning", "duplicates": _duplicate_response(matches)}, status=409)
    try:
        if matches and duplicate_action == "merge":
            lead = _apply_payload(matches[0][1], payload, access.organization, partial=True)
            return Response(lead_to_dict(lead), status=200)
        lead = _apply_payload(Lead(project=getattr(request, "project", None)), payload, access.organization)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(lead_to_dict(lead), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def merge_lead(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    _require_manual_lead_creation(access)
    lead_id = request.data.get("existing_lead_id")
    if not lead_id:
        return Response({"existing_lead_id": ["This field is required."]}, status=400)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    payload = request.data.copy()
    payload.pop("existing_lead_id", None)
    try:
        lead = _apply_payload(lead, payload, access.organization, partial=True)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(lead_to_dict(lead))


def _provider_sync(request, organization_slug, provider):
    access = get_organization_access(request.user, organization_slug)
    _require_ad_or_import_management(access)
    incoming = request.data.get("leads") if isinstance(request.data.get("leads"), list) else [request.data]
    synced = []
    created = 0
    for item in incoming:
        payload = dict(item)
        external_id = payload.pop("external_lead_id", None) or payload.pop("lead_id", None) or payload.pop("id", None)
        if not external_id:
            return Response({"external_lead_id": ["This field is required for provider sync."]}, status=400)
        payload.setdefault("source", "fb" if provider == "meta" else "website")
        lead = Lead.all_objects.filter(
            organization=access.organization, external_source=provider, external_lead_id=str(external_id)
        ).first()
        was_created = lead is None
        try:
            lead = _apply_payload(lead or Lead(project=getattr(request, "project", None)), payload, access.organization, partial=not was_created, save=False)
            lead.external_source = provider
            lead.external_lead_id = str(external_id)
            lead.project = getattr(request, "project", None)
            lead.save()
        except (ValidationError, ValueError, TypeError) as error:
            return _validation_response(error)
        created += int(was_created)
        synced.append(lead_to_dict(lead))
    return Response({"provider": provider, "created": created, "updated": len(synced) - created, "results": synced}, status=201 if created else 200)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_meta(request, organization_slug):
    return _provider_sync(request, organization_slug, "meta")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_google(request, organization_slug):
    return _provider_sync(request, organization_slug, "google")

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
        leads = leads.filter(status=status_filter)
    if source := request.query_params.get("source"):
        leads = leads.filter(source=source)
    if owner := request.query_params.get("owner") or request.query_params.get("owner_id"):
        leads = leads.filter(assigned_membership_id=owner)
    if city := request.query_params.get("city"):
        leads = leads.filter(city__icontains=city)
    if date_from := request.query_params.get("date_from"):
        leads = leads.filter(created_at__date__gte=date_from)
    if date_to := request.query_params.get("date_to"):
        leads = leads.filter(created_at__date__lte=date_to)
    if score_min := request.query_params.get("score_min"):
        leads = leads.filter(score__gte=score_min)
    if score_max := request.query_params.get("score_max"):
        leads = leads.filter(score__lte=score_max)
    if tag := request.query_params.get("tag"):
        leads = leads.filter(tags__tag_name=tag)
    if search := request.query_params.get("search"):
        leads = leads.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )
    ordering = request.query_params.get("ordering", "-created_at")
    allowed_ordering = {"created_at", "score", "first_name", "city", "status", "updated_at"}
    if ordering.lstrip("-") not in allowed_ordering:
        return Response({"ordering": ["Use created_at, score, first_name, city, status, or updated_at."]}, status=400)
    leads = leads.order_by(ordering, "id")
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
    except (TypeError, ValueError):
        return Response({"page": ["Page and page_size must be integers."]}, status=400)
    count = leads.count()
    start = (page - 1) * page_size
    rows = leads[start:start + page_size]
    return Response({
        "count": count,
        "page": page,
        "page_size": page_size,
        "next": page + 1 if start + page_size < count else None,
        "previous": page - 1 if page > 1 else None,
        "results": [lead_to_dict(lead) for lead in rows],
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

    if "status" in request.data:
        return Response({"status": ["Use the lead status transition endpoint."]}, status=status.HTTP_400_BAD_REQUEST)
    if "assigned_membership" in request.data and str(request.data.get("assigned_membership")) != str(lead.assigned_membership_id):
        return Response({"assigned_membership": ["Use the assignment endpoint with a reason."]}, status=status.HTTP_400_BAD_REQUEST)
    converted_core_fields = {"first_name", "last_name", "email", "phone", "alt_phone", "address", "city", "occupation", "source", "score"}
    if lead.status == "converted" and converted_core_fields.intersection(request.data):
        return Response({"status": ["Converted lead core fields are immutable."]}, status=409)

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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lead_status(request, organization_slug, lead_id):
    """FR-P5-02/API-P5-05: guarded lifecycle transition with immutable history."""
    access = get_organization_access(request.user, organization_slug)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    try:
        updated = transition_lead_status(
            lead_id=lead.id, new_status=str(request.data.get("status", "")).strip(), actor=request.user, organization=access.organization
        )
    except (ValidationError, ProtectedError) as error:
        return _validation_response(error)
    return Response(lead_to_dict(updated, include_follow_ups=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def bulk_action(request, organization_slug):
    """FR-P5-04/API-P5-06: execute one transactional action over selected leads."""
    access = get_organization_access(request.user, organization_slug)
    lead_ids = request.data.get("lead_ids")
    action = request.data.get("action")
    if not isinstance(lead_ids, list) or not lead_ids or len(set(lead_ids)) != len(lead_ids):
        return Response({"lead_ids": ["Provide a non-empty list of unique lead IDs."]}, status=400)
    allowed_actions = {"assign", "change_status", "add_tag", "export", "delete"}
    if action not in allowed_actions:
        return Response({"action": [f"Use one of: {', '.join(sorted(allowed_actions))}."]}, status=400)
    if action in {"assign", "delete"} and not access.is_platform and membership_role_code(access.membership) not in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER}:
        raise PermissionDenied("Only Managers and Admins may perform this bulk action.")
    leads = list(_leads_for_access(access).filter(pk__in=lead_ids).select_for_update())
    if len(leads) != len(lead_ids):
        raise PermissionDenied("One or more selected leads are outside your permitted scope.")
    if action == "export":
        from django.http import HttpResponse
        response = HttpResponse("id,full_name,phone,status,owner\n", content_type="text/csv")
        for lead in leads:
            response.write(f'{lead.id},"{lead.full_name.replace(chr(34), chr(34) * 2)}",{lead.phone},{lead.status},{lead.assigned_membership_id or ""}\n')
        response["Content-Disposition"] = 'attachment; filename="leads.csv"'
        return response
    try:
        if action == "assign":
            target = OrganizationMembership.objects.filter(
                pk=request.data.get("telecaller_membership"), organization=access.organization,
                role=OrganizationMembership.Role.TELECALLER, is_active=True,
            ).first()
            if target is None:
                raise ValidationError({"telecaller_membership": "Use an active telecaller in this organization."})
            for lead in leads:
                assign_lead_lifecycle(lead_id=lead.id, membership=target, reason=request.data.get("reason"), actor=request.user, organization=access.organization)
        elif action == "change_status":
            for lead in leads:
                transition_lead_status(lead_id=lead.id, new_status=str(request.data.get("status", "")).strip(), actor=request.user, organization=access.organization)
        elif action == "add_tag":
            tag_name = str(request.data.get("tag", "")).strip()
            if not tag_name:
                raise ValidationError({"tag": "This field is required."})
            for lead in leads:
                LeadTag.objects.get_or_create(lead=lead, tag_name=tag_name)
        elif action == "delete":
            Lead.all_objects.filter(pk__in=lead_ids, organization=access.organization).delete()
    except (ValidationError, ProtectedError) as error:
        transaction.set_rollback(True)
        return _validation_response(error)
    return Response({"action": action, "affected": len(leads)})


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
    return _record_follow_up(access, lead, request.data)


@transaction.atomic
def _record_follow_up(access, lead, payload):
    """API-P6-04: create or update one scheduled caller-owned follow-up."""
    if access.membership is None:
        raise PermissionDenied("A membership in this organization is required to schedule a follow-up.")
    try:
        call = FollowUpCall.objects.select_for_update().filter(organization=access.organization, lead=lead, telecaller_membership=access.membership, called_at__isnull=True).order_by("created_at", "id").first()
        if call:
            _schedule_follow_up(call, payload)
            response_status = status.HTTP_200_OK
        else:
            call = FollowUpCall(organization=access.organization, lead=lead, telecaller_membership=access.membership)
            _schedule_follow_up(call, payload)
            response_status = status.HTTP_201_CREATED
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)
    return Response(follow_up_to_dict(call), status=response_status)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def telecalling_follow_ups(request, organization_slug):
    """API-P6-04: create or update a scheduled follow-up for an assigned lead."""
    access = get_organization_access(request.user, organization_slug)
    try:
        lead_id = int(request.data.get("lead_id"))
        if lead_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"lead_id": ["A positive integer is required."]}, status=status.HTTP_400_BAD_REQUEST)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    payload = request.data.copy()
    payload.pop("lead_id", None)
    return _record_follow_up(access, lead, payload)


def _queue_page_url(request, page, page_size):
    query = request.query_params.copy()
    query["page"] = page
    query["page_size"] = page_size
    return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_queue(request, organization_slug):
    """FR-P6-01: return the current dynamically ordered calling queue."""
    access = get_organization_access(request.user, organization_slug)
    tab = request.query_params.get("tab", "assigned")
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        queue = get_call_queue(access, tab=tab)
    except (ValidationError, ValueError, TypeError) as error:
        return _validation_response(error)

    count = queue.count()
    start = (page - 1) * page_size
    results = queue[start:start + page_size]
    return Response({
        "count": count,
        "next": _queue_page_url(request, page + 1, page_size) if start + page_size < count else None,
        "previous": _queue_page_url(request, page - 1, page_size) if page > 1 else None,
        "page": page,
        "page_size": page_size,
        "tab": tab,
        "results": [call_queue_item_to_dict(call) for call in results],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_analytics(request, organization_slug):
    """FR-P6-07 / API-P6-05: return organization team call analytics."""
    access = get_organization_access(request.user, organization_slug)
    if not access.can_view_all_leads:
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can view team analytics.")
    return Response(get_team_call_analytics(access))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def telecalling_redistribute(request, organization_slug):
    """FR-P6-07: atomically redistribute idle current queue items."""
    access = get_organization_access(request.user, organization_slug)
    if not access.can_manage_leads:
        raise PermissionDenied("Only managers, organization admins, and authorized platform users can redistribute queues.")

    raw_call_ids = request.data.get("call_ids")
    if not isinstance(raw_call_ids, list) or not raw_call_ids:
        return Response({"call_ids": ["Provide a non-empty list of call IDs."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        call_ids = [int(call_id) for call_id in raw_call_ids]
        target_id = int(request.data.get("telecaller_membership_id"))
        if any(call_id <= 0 for call_id in call_ids) or target_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"detail": "Call IDs and telecaller_membership_id must be positive integers."}, status=status.HTTP_400_BAD_REQUEST)
    if len(set(call_ids)) != len(call_ids):
        return Response({"call_ids": ["Duplicate call IDs are not allowed."]}, status=status.HTTP_400_BAD_REQUEST)

    try:
        target, calls = redistribute_call_queue(
            access=access,
            call_ids=call_ids,
            telecaller_membership_id=target_id,
        )
    except ValidationError as error:
        return _validation_response(error)
    return Response({
        "redistributed": len(calls),
        "call_ids": [call.id for call in calls],
        "telecaller": membership_to_dict(target),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_dispositions(request, organization_slug):
    """FR-P6-03: list the active fixed disposition catalogue for this organization."""
    access = get_organization_access(request.user, organization_slug)
    dispositions = active_call_dispositions(access.organization)
    return Response({
        "count": dispositions.count(),
        "results": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "color": item.color,
                "description": item.description,
                "sort_order": item.sort_order,
            }
            for item in dispositions
        ],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def telecalling_call_log(request, organization_slug):
    """FR-P6-02/04/05/06/08 and API-P6-06: submit one manual call log."""
    access = get_organization_access(request.user, organization_slug)
    try:
        lead_id = int(request.data.get("lead_id"))
        if lead_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"lead_id": ["A positive integer is required."]}, status=status.HTTP_400_BAD_REQUEST)
    lead = get_object_or_404(_leads_for_access(access), pk=lead_id)
    try:
        raw_call_timestamp = request.data.get("call_timestamp")
        call_timestamp = (
            _parse_datetime(raw_call_timestamp, "call_timestamp")
            if raw_call_timestamp not in (None, "") else None
        )
        raw_next_follow_up = request.data.get("next_follow_up")
        next_follow_up = (
            _parse_datetime(raw_next_follow_up, "next_follow_up")
            if raw_next_follow_up not in (None, "") else None
        )
        call, created = log_manual_call(
            access=access,
            lead=lead,
            disposition=request.data.get("disposition"),
            notes=request.data.get("notes"),
            call_timestamp=call_timestamp,
            next_follow_up=next_follow_up,
            call_recording=request.FILES.get("call_recording"),
        )
    except ValidationError as error:
        return _validation_response(error)
    log_audit(
        request=request,
        organization=access.organization,
        module="telecalling",
        action="manual_call_logged",
        details={
            "lead_id": lead.id,
            "disposition": call.outcome,
            "call_timestamp": call.called_at.isoformat(),
            "has_recording": bool(call.call_recording),
        },
        target=call,
    )
    return Response(
        manual_call_log_to_dict(call, request=request),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


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
    if lead.status in {"lost", "converted"}:
        return Response({"lead": "Only active leads can have a site visit scheduled."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        visit_date = _parse_date(request.data.get("visit_date"), "visit_date")
        visit_time = _parse_time(request.data.get("visit_time"), "visit_time")
        _schedule_validation(visit_date, visit_time, organization=access.organization, project_id=lead.project_id)
        executive = _active_executive(access.organization, request.data.get("executive"))
        role = membership_role_code(access.membership)
        if role in {"site_visit_exec", "site_visit_executive"} and executive.id != access.membership.id:
            raise PermissionDenied("Site Visit Executives may schedule only their own visits.")
        if not str(request.data.get("site", "")).strip():
            raise ValidationError({"site": "This field is required."})
        duration = request.data.get("duration_minutes", 60)
        try:
            duration = int(duration)
        except (TypeError, ValueError) as error:
            raise ValidationError({"duration_minutes": "Use a whole number of minutes."}) from error
        if duration <= 0:
            raise ValidationError({"duration_minutes": "Duration must be greater than zero."})
        with transaction.atomic():
            _ensure_executive_available(
                organization=access.organization,
                executive=executive,
                visit_date=visit_date,
                visit_time=visit_time,
                duration_minutes=duration,
            )
            site_visit = Sitevisit(
                organization=access.organization, lead=lead, executive_membership=executive,
                visit_date=visit_date, visit_time=visit_time, duration_minutes=duration,
                site=request.data.get("site"), location=request.data.get("location"),
                customer_preference=request.data.get("customer_preference"), notes=request.data.get("notes"),
                created_by=request.user, status=Sitevisit.Status.UPCOMING,
            )
            site_visit.full_clean()
            site_visit.save()
    except (ValidationError, PermissionDenied, ValueError, TypeError) as exc:
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
            transaction.set_rollback(True)
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
    try:
        validate_site_visit_outcome(access.organization, outcome)
    except ValidationError as exc:
        return _validation_response(exc)
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
            lead = Lead.all_objects.select_for_update().get(
                pk=visit.lead_id,
                organization=access.organization,
            )
            lead = _complete_lead_for_site_visit(
                lead=lead,
                actor=request.user,
                organization=access.organization,
            )
            lead.score = (lead.score or 0) + 20
            lead.save(update_fields=["score", "updated_at"])
        except ValidationError as exc:
            transaction.set_rollback(True)
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
