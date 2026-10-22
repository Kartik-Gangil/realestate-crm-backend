import os
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.services import get_organization_access, get_project_context
from core.files import AUDIO_KINDS, private_file_response, validate_upload
from .models import FollowUpCall, Lead
from .serializers import follow_up_to_dict, lead_to_dict

MAX_RECORDING_SIZE = 25 * 1024 * 1024
ALLOWED_DISPOSITIONS = {
    "Interested", "Callback Later", "Busy", "No Answer", "Switched Off", "Wrong Number", "DND", "Already Purchased",
}
FOLLOW_UP_REQUIRED = {"Interested", "Callback Later"}
ALLOWED_CALL_STATUSES = {value for value, _label in FollowUpCall.Status.choices}
DISPOSITION_TO_OUTCOME = {
    "Interested": "Interested",
    "Callback Later": "Callback Later",
    "Busy": "busy",
    "No Answer": "no_answer",
    "Switched Off": "Switched Off",
    "Wrong Number": "Wrong Number",
    "DND": "DND",
    "Already Purchased": "Already Purchased",
}


def _queue_leads(access, project):
    leads = Lead.objects.filter(organization=access.organization, project=project).select_related("assigned_membership__user")
    if not access.can_view_all_leads:
        leads = leads.filter(assigned_membership=access.membership)
    follow_ups = FollowUpCall.objects.filter(lead=OuterRef("pk"))
    pending_filter = Q(follow_up_calls__called_at__isnull=True)
    follow_up_count_filter = Q(follow_up_calls__next_follow_up__isnull=False)
    if not access.can_view_all_leads:
        follow_ups = follow_ups.filter(telecaller_membership=access.membership)
        pending_filter &= Q(follow_up_calls__telecaller_membership=access.membership)
        follow_up_count_filter &= Q(follow_up_calls__telecaller_membership=access.membership)
    latest_status = follow_ups.filter(called_at__isnull=False).order_by("-called_at", "-id").values("status")[:1]
    return leads.annotate(
        pending_attempts=Count("follow_up_calls", filter=pending_filter),
        next_follow_up_at=Count("follow_up_calls", filter=follow_up_count_filter),
        latest_call_status=Subquery(latest_status),
    ).order_by("-pending_attempts", "-updated_at", "id")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_queue(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    leads = _queue_leads(access, project)
    return Response({
        "count": leads.count(),
        "results": [
            lead_to_dict(
                lead,
                latest_follow_up_status=("new" if lead.pending_attempts else (lead.latest_call_status or "new")),
            )
            | {"pending_attempts": lead.pending_attempts}
            for lead in leads
        ],
    })


def _parse_timestamp(value):
    if not value:
        return timezone.now()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


@api_view(["POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def telecalling_call_log(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    if access.membership is None:
        return Response({"detail": "An organization membership is required."}, status=status.HTTP_403_FORBIDDEN)
    lead = Lead.objects.filter(organization=access.organization, project=project, pk=request.data.get("lead_id"))
    if not access.can_view_all_leads:
        lead = lead.filter(assigned_membership=access.membership)
    lead = lead.first()
    if lead is None:
        return Response({"detail": "Lead is not assigned to this telecaller."}, status=status.HTTP_404_NOT_FOUND)

    disposition = str(request.data.get("disposition", "")).strip()
    requested_status = str(request.data.get("status", "")).strip() or FollowUpCall.Status.CONTACTED
    notes = str(request.data.get("notes", "")).strip()
    next_follow_up = request.data.get("next_follow_up")
    if disposition not in ALLOWED_DISPOSITIONS:
        return Response({"disposition": ["Select a valid disposition."]}, status=status.HTTP_400_BAD_REQUEST)
    if disposition in FOLLOW_UP_REQUIRED and not next_follow_up:
        return Response({"next_follow_up": ["A follow-up date is required for this disposition."]}, status=status.HTTP_400_BAD_REQUEST)
    if requested_status not in ALLOWED_CALL_STATUSES:
        return Response({"status": ["Select a valid lead status."]}, status=status.HTTP_400_BAD_REQUEST)
    if requested_status == FollowUpCall.Status.NEW:
        requested_status = FollowUpCall.Status.CONTACTED
    recording = request.FILES.get("recording") or request.FILES.get("call_recording")
    if recording:
        try:
            validate_upload(recording, kinds=AUDIO_KINDS, max_bytes=MAX_RECORDING_SIZE, field="recording")
        except ValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
    if recording and recording.name.lower().rsplit(".", 1)[-1] not in {"mp3", "wav", "m4a", "aac"}:
        return Response({"recording": ["Only MP3, WAV, M4A, and AAC recordings are supported."]}, status=status.HTTP_400_BAD_REQUEST)

    call = FollowUpCall.objects.filter(organization=access.organization, lead=lead, telecaller_membership=access.membership, called_at__isnull=True).order_by("created_at", "id").first()
    if call is None:
        call = FollowUpCall(organization=access.organization, lead=lead, telecaller_membership=access.membership)
    call.note = notes
    call.outcome = DISPOSITION_TO_OUTCOME[disposition]
    call.status = requested_status
    call.called_at = _parse_timestamp(request.data.get("call_timestamp"))
    call.next_follow_up = _parse_timestamp(next_follow_up) if next_follow_up else None
    call.call_recording = recording or call.call_recording
    call.full_clean()
    call.save()
    response_data = follow_up_to_dict(call)
    response_data["disposition"] = disposition
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_analytics(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    calls = FollowUpCall.objects.filter(organization=access.organization, lead__project=project)
    if not access.can_view_all_leads:
        calls = calls.filter(telecaller_membership=access.membership)
    today = timezone.localdate()
    return Response({"calls_today": calls.filter(called_at__date=today).count(), "connected": calls.filter(outcome__in=["Interested", "connected"]).count(), "follow_ups_due": calls.filter(next_follow_up__date__lte=today, next_follow_up__isnull=False).count()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telecalling_call_recording(request, organization_slug, call_id):
    access = get_organization_access(request.user, organization_slug)
    project = get_project_context(request, access)
    calls = FollowUpCall.objects.filter(organization=access.organization, lead__project=project)
    if not access.can_view_all_leads:
        calls = calls.filter(telecaller_membership=access.membership)
    call = get_object_or_404(calls, pk=call_id)
    return private_file_response(call.call_recording, filename=os.path.basename(call.call_recording.name or "") or "recording")
