from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from core.endpoint import crm_endpoint
from core.models import Notification
from organizations.services import get_organization_access, is_organization_admin
from organizations.models import ProjectAssignment


def _visible_notifications(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    memberships = access.organization.memberships.filter(user=request.user, is_active=True)
    queryset = Notification.objects.filter(
        organization=access.organization,
        recipient_membership__in=memberships,
    )
    if not access.is_platform and not is_organization_admin(access.membership):
        project_ids = ProjectAssignment.objects.filter(
            membership=access.membership,
        ).values("project_id")
        queryset = queryset.filter(Q(project__isnull=True) | Q(project_id__in=project_ids))
    return queryset.order_by("-created_at", "-id"), access


def _notification_to_dict(notification):
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "related_object_type": notification.related_object_type or None,
        "related_object_id": notification.related_object_id,
        "project_id": notification.project_id,
        "status": notification.status,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


@crm_endpoint(["GET"], scope="organization")
def notification_list(request, organization_slug):
    queryset, _ = _visible_notifications(request, organization_slug)
    status_filter = request.query_params.get("status")
    if status_filter:
        if status_filter not in Notification.Status.values:
            return Response({"status": ["Use pending or read."]}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(status=status_filter)
    try:
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("page_size", "25"))))
    except ValueError:
        return Response({"page": ["page and page_size must be integers."]}, status=status.HTTP_400_BAD_REQUEST)
    count = queryset.count()
    start = (page - 1) * page_size
    return Response({
        "count": count,
        "page": page,
        "page_size": page_size,
        "results": [_notification_to_dict(item) for item in queryset[start:start + page_size]],
    })


@crm_endpoint(["POST"], scope="organization")
def notification_mark_read(request, organization_slug, notification_id):
    queryset, _ = _visible_notifications(request, organization_slug)
    notification = get_object_or_404(queryset, pk=notification_id)
    if notification.status != Notification.Status.READ:
        notification.status = Notification.Status.READ
        notification.read_at = timezone.now()
        notification.save(update_fields=["status", "read_at"])
    return Response(_notification_to_dict(notification))


@crm_endpoint(["POST"], scope="organization")
def notification_mark_all_read(request, organization_slug):
    queryset, _ = _visible_notifications(request, organization_slug)
    updated = queryset.filter(status=Notification.Status.PENDING).update(
        status=Notification.Status.READ,
        read_at=timezone.now(),
    )
    return Response({"updated": updated})
