from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inventory.models import Payment, PlotBooking
from leads.models import Lead, Sitevisit
from organizations.services import get_organization_access, has_permission, membership_role_code
from documents.models import CustomerDocument

from .models import Customer, CustomerNote
from .services import create_customer_from_lead, duplicate_customer


def _access(request, slug):
    return get_organization_access(request.user, slug)


def _can_manage(access):
    return access.is_platform or has_permission(access.membership.user, access.organization, "customers.edit")


def _can_view(access, customer):
    if access.is_platform or membership_role_code(access.membership) in {"admin", "manager"}:
        return True
    return customer.lead_id and customer.lead.assigned_membership_id == access.membership.id


def _data(customer):
    return {
        "id": customer.id, "customer_code": customer.customer_code, "lead_id": customer.lead_id,
        "full_name": customer.full_name, "phone": customer.phone, "email": customer.email,
        "government_id": customer.government_id or None, "address": customer.address,
        "status": customer.status, "status_reason": customer.status_reason or None,
        "created_at": customer.created_at.isoformat(), "updated_at": customer.updated_at.isoformat(),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def customer_list(request, organization_slug):
    access = _access(request, organization_slug)
    query = Customer.objects.filter(organization=access.organization).select_related("lead", "lead__assigned_membership")
    if not (access.is_platform or membership_role_code(access.membership) in {"admin", "manager"}):
        query = query.filter(lead__assigned_membership=access.membership)
    if request.method == "GET":
        search = str(request.query_params.get("search", "")).strip()
        if search:
            query = query.filter(full_name__icontains=search) | query.filter(phone__icontains=search)
        return Response({"count": query.count(), "results": [_data(item) for item in query.order_by("-created_at")]})
    if not _can_manage(access):
        raise PermissionDenied("Only managers and admins can create customers.")
    payload = request.data
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        return Response({"phone": ["This field is required."]}, status=400)
    existing = duplicate_customer(organization=access.organization, phone=phone, email=str(payload.get("email", "")).strip(), government_id=str(payload.get("government_id", "")).strip())
    if existing:
        return Response({"detail": "A matching customer already exists.", "existing_customer_id": existing.id, "existing_customer_url": f"/api/v1/organizations/{organization_slug}/customers/{existing.id}/360/"}, status=409)
    customer = Customer.objects.create(
        organization=access.organization, full_name=str(payload.get("full_name", "")).strip(),
        phone=phone, email=str(payload.get("email", "")).strip(),
        government_id=str(payload.get("government_id", "")).strip(), address=str(payload.get("address", "")).strip(),
    )
    return Response(_data(customer), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def customer_detail(request, organization_slug, customer_id):
    access = _access(request, organization_slug)
    customer = get_object_or_404(Customer.objects.filter(organization=access.organization).select_related("lead", "lead__assigned_membership"), pk=customer_id)
    if not _can_view(access, customer):
        raise PermissionDenied("This customer is not assigned to you.")
    if request.method == "GET":
        return Response(_data(customer))
    if not _can_manage(access):
        raise PermissionDenied("Only managers and admins can edit customers.")
    allowed = {"full_name", "phone", "email", "government_id", "address", "status", "status_reason"}
    for field in allowed & set(request.data):
        setattr(customer, field, request.data[field])
    if customer.status in {Customer.Status.INACTIVE, Customer.Status.BLACKLISTED} and not customer.status_reason.strip():
        return Response({"status_reason": ["A reason is required."]}, status=400)
    duplicate = duplicate_customer(organization=access.organization, phone=customer.phone, email=customer.email, government_id=customer.government_id, exclude_id=customer.id)
    if duplicate:
        return Response({"detail": "A matching customer already exists.", "existing_customer_id": duplicate.id}, status=409)
    customer.save()
    return Response(_data(customer))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_360(request, organization_slug, customer_id):
    access = _access(request, organization_slug)
    customer = get_object_or_404(Customer.objects.filter(organization=access.organization).select_related("lead", "lead__assigned_membership"), pk=customer_id)
    if not _can_view(access, customer):
        raise PermissionDenied("This customer is not assigned to you.")
    bookings = PlotBooking.objects.filter(organization=access.organization, lead_id=customer.lead_id).select_related("plot", "plot__block")
    payments = Payment.objects.filter(organization=access.organization, booking__lead_id=customer.lead_id)
    documents = CustomerDocument.objects.filter(organization=access.organization, customer_id=customer.lead_id, is_active=True)
    visits = Sitevisit.objects.filter(organization=access.organization, lead_id=customer.lead_id)
    notes = list(customer.notes.select_related("author").all())
    timeline = []
    for item in bookings:
        timeline.append({"type": "booking", "id": item.id, "at": item.created_at.isoformat(), "status": item.status})
    for item in payments:
        timeline.append({"type": "payment", "id": item.id, "at": item.created_at.isoformat(), "amount": str(item.amount), "status": item.status})
    for item in visits:
        timeline.append({"type": "site_visit", "id": item.id, "at": item.created_at.isoformat(), "status": item.status})
    for item in documents:
        timeline.append({"type": "document", "id": item.id, "at": item.created_at.isoformat(), "status": item.status})
    for item in notes:
        timeline.append({"type": "note", "id": item.id, "at": item.created_at.isoformat(), "text": item.note_text})
    timeline.sort(key=lambda item: item["at"])
    total_paid = sum((payment.amount for payment in payments if payment.status == Payment.Status.SUCCESS), Decimal("0"))
    total_dues = sum((booking.final_price or Decimal("0") for booking in bookings if booking.status == PlotBooking.Status.CONFIRMED), Decimal("0"))
    return Response({"customer": _data(customer), "summary": {"bookings": bookings.count(), "payments": payments.count(), "documents": documents.count(), "notes": len(notes), "total_paid": str(total_paid), "outstanding": str(max(total_dues - total_paid, Decimal("0")))}, "timeline": timeline})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def customer_notes(request, organization_slug, customer_id):
    access = _access(request, organization_slug)
    customer = get_object_or_404(Customer.objects.filter(organization=access.organization).select_related("lead", "lead__assigned_membership"), pk=customer_id)
    if not _can_view(access, customer):
        raise PermissionDenied("This customer is not assigned to you.")
    text = str(request.data.get("note_text", "")).strip()
    if not text:
        return Response({"note_text": ["This field is required."]}, status=400)
    note = CustomerNote.objects.create(organization=access.organization, customer=customer, author=request.user, note_text=text)
    return Response({"id": note.id, "note_text": note.note_text, "created_at": note.created_at.isoformat()}, status=201)
