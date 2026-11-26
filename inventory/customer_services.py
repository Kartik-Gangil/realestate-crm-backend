import hashlib
import hmac
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.crypto import decrypt_bytes, encrypt_bytes
from leads.models import Lead, Sitevisit
from leads.phone import normalize_phone
from organizations.services import is_organization_admin, membership_role_code

from .models import Customer, CustomerCodeSequence, CustomerNote, Payment, PlotBooking
from .phase5_services import payment_totals


LIFECYCLE_RANK = {
    Customer.Status.NEW: 0,
    Customer.Status.ACTIVE: 1,
    Customer.Status.ENGAGED: 2,
    Customer.Status.CONVERTED: 3,
}


class CustomerDuplicateError(ValidationError):
    code = "customer_duplicate"


def normalize_customer_email(value):
    return str(value or "").strip().lower()


def normalize_government_id(id_type, value):
    if not value:
        return ""
    normalized_type = str(id_type or "").strip().lower()
    compact = re.sub(r"\s+", "", str(value).upper())
    if normalized_type == Customer.GovernmentIdType.AADHAAR:
        if not compact.isdigit() or len(compact) != 12:
            raise ValidationError({"government_id": "Aadhaar must contain 12 digits."})
    elif normalized_type == Customer.GovernmentIdType.PAN:
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", compact):
            raise ValidationError({"government_id": "PAN must use the valid 10-character format."})
    else:
        raise ValidationError({"government_id_type": "Use Aadhaar or PAN."})
    return compact


def government_id_hash(value):
    key = str(settings.SECRET_KEY).encode("utf-8")
    return hmac.new(key, str(value).encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_government_id(value):
    return encrypt_bytes(value.encode("utf-8")).hex()


def decrypt_government_id(value):
    return decrypt_bytes(bytes.fromhex(value)).decode("utf-8")


def _identity_query(project, *, phone="", email="", government_id_hash_value="", exclude_id=None):
    identity_queries = []
    if phone:
        identity_queries.append(Q(phone=phone))
    if email:
        identity_queries.append(Q(email__iexact=email))
    if government_id_hash_value:
        identity_queries.append(Q(government_id_hash=government_id_hash_value))
    # An empty create/update payload must go through model validation. An
    # empty Q() matches every customer and incorrectly turns it into a
    # duplicate response when the project already has any customer.
    queryset = Customer.objects.filter(project=project)
    if identity_queries:
        query = identity_queries[0]
        for identity_query in identity_queries[1:]:
            query |= identity_query
        queryset = queryset.filter(query)
    else:
        queryset = queryset.none()
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset.order_by("id")


def find_customer_collisions(project):
    """Return collision counts only; never expose customer identity values."""
    rows = {"phone": 0, "email": 0, "government_id_hash": 0}
    for field in rows:
        values = (
            Customer.objects.filter(project=project)
            .exclude(**{field: ""})
            .values(field)
            .annotate(row_count=__import__("django.db.models", fromlist=["Count"]).Count("id"))
            .filter(row_count__gt=1)
        )
        rows[field] = values.count()
    return rows


def _raise_duplicate(existing):
    error = CustomerDuplicateError({
        "detail": "A customer with the same phone, email, or government ID already exists.",
        "existing_customer_id": str(existing.pk),
        "existing_customer_code": existing.customer_code,
        "existing_customer_url": f"/customers/{existing.pk}",
    })
    error.code = "customer_duplicate"
    raise error


def _next_customer_code(project):
    sequence, _ = CustomerCodeSequence.objects.select_for_update().get_or_create(
        project=project, defaults={"next_number": 1}
    )
    sequence = CustomerCodeSequence.objects.select_for_update().get(pk=sequence.pk)
    number = sequence.next_number
    sequence.next_number += 1
    sequence.save(update_fields=["next_number"])
    return f"{project.code}-C-{number:06d}"


def create_customer(*, organization, project, full_name, phone="", email="", address="", lead=None,
                    government_id_type="", government_id="", actor=None, customer_code=None):
    if project.organization_id != organization.id:
        raise ValidationError({"project": "Project must belong to this organization."})
    if lead is not None and (lead.organization_id != organization.id or lead.project_id != project.id):
        raise ValidationError({"lead": "Lead must belong to the selected organization and project."})
    normalized_phone = normalize_phone(phone) if phone else ""
    if phone and normalized_phone is None:
        raise ValidationError({"phone": "Phone number cannot be normalized."})
    normalized_email = normalize_customer_email(email)
    normalized_id = normalize_government_id(government_id_type, government_id)
    hashed_id = government_id_hash(normalized_id) if normalized_id else ""
    with transaction.atomic():
        existing = _identity_query(
            project,
            phone=normalized_phone,
            email=normalized_email,
            government_id_hash_value=hashed_id,
        ).first()
        if existing:
            _raise_duplicate(existing)
        customer = Customer(
            organization=organization,
            project=project,
            lead=lead,
            customer_code=customer_code or _next_customer_code(project),
            full_name=str(full_name or "").strip(),
            phone=normalized_phone or "",
            email=normalized_email,
            address=str(address or "").strip(),
            status=Customer.Status.NEW,
            government_id_type=str(government_id_type or "").strip().lower(),
            government_id_encrypted=encrypt_government_id(normalized_id) if normalized_id else "",
            government_id_hash=hashed_id,
            government_id_last4=normalized_id[-4:] if normalized_id else "",
            lifecycle_changed_at=timezone.now(),
            lifecycle_changed_by=actor,
        )
        customer.full_clean()
        customer.save()
        return customer


def update_customer_identity(customer, *, phone=None, email=None, government_id_type=None, government_id=None):
    """Update customer identity fields while preserving application-level uniqueness."""
    normalized_phone = customer.phone if phone is None else (normalize_phone(phone) if phone else "")
    if phone and normalized_phone is None:
        raise ValidationError({"phone": "Phone number cannot be normalized."})
    normalized_email = customer.email if email is None else normalize_customer_email(email)
    selected_type = customer.government_id_type if government_id_type is None else str(government_id_type or "").strip().lower()
    supplied_id = government_id is not None
    normalized_id = normalize_government_id(selected_type, government_id) if supplied_id and government_id else (decrypt_government_id(customer.government_id_encrypted) if customer.government_id_encrypted else "")
    hashed_id = government_id_hash(normalized_id) if normalized_id else ""
    duplicate = _identity_query(
        customer.project,
        phone=normalized_phone,
        email=normalized_email,
        government_id_hash_value=hashed_id,
        exclude_id=customer.pk,
    ).first()
    if duplicate:
        _raise_duplicate(duplicate)
    customer.phone = normalized_phone or ""
    customer.email = normalized_email
    if government_id is not None or government_id_type is not None:
        customer.government_id_type = selected_type if normalized_id else ""
        customer.government_id_encrypted = encrypt_government_id(normalized_id) if normalized_id else ""
        customer.government_id_hash = hashed_id
        customer.government_id_last4 = normalized_id[-4:] if normalized_id else ""
    customer.save(update_fields=["phone", "email", "government_id_type", "government_id_encrypted", "government_id_hash", "government_id_last4", "updated_at"])
    return customer


def advance_customer_lifecycle(customer, target_status, *, reason="Automatic lifecycle transition", actor=None):
    if target_status not in LIFECYCLE_RANK:
        raise ValidationError({"status": "Automatic lifecycle transitions use New, Active, Engaged, or Converted."})
    with transaction.atomic():
        current = Customer.objects.select_for_update().get(pk=customer.pk)
        if current.status in {Customer.Status.INACTIVE, Customer.Status.BLACKLISTED}:
            return current
        if LIFECYCLE_RANK[target_status] <= LIFECYCLE_RANK.get(current.status, 0):
            return current
        current.status = target_status
        current.lifecycle_reason = reason
        current.lifecycle_changed_at = timezone.now()
        current.lifecycle_changed_by = actor
        current.save(update_fields=["status", "lifecycle_reason", "lifecycle_changed_at", "lifecycle_changed_by", "updated_at"])
        return current


def _can_change_customer_status(actor, customer):
    if actor is None or not actor.is_authenticated:
        return False
    if actor.is_superuser:
        return True
    membership = customer.organization.memberships.filter(user=actor, is_active=True).select_related("organization_role").first()
    return bool(membership and (is_organization_admin(membership) or membership_role_code(membership) == "manager"))


def set_customer_status(customer, status, reason, actor):
    if status not in Customer.Status.values:
        raise ValidationError({"status": "Use a valid customer status."})
    if not _can_change_customer_status(actor, customer):
        raise PermissionDenied("Only Managers and Admins may change customer lifecycle status.")
    reason = str(reason or "").strip()
    if status in {Customer.Status.INACTIVE, Customer.Status.BLACKLISTED} or customer.status in {Customer.Status.INACTIVE, Customer.Status.BLACKLISTED}:
        if not reason:
            raise ValidationError({"reason": "A reason is required for customer lifecycle changes."})
    customer.status = status
    customer.lifecycle_reason = reason
    customer.lifecycle_changed_at = timezone.now()
    customer.lifecycle_changed_by = actor
    customer.save(update_fields=["status", "lifecycle_reason", "lifecycle_changed_at", "lifecycle_changed_by", "updated_at"])
    return customer


def customer_queryset_for_access(access, project):
    queryset = Customer.objects.filter(organization=access.organization, project=project).select_related("lead", "project")
    if access.is_platform or is_organization_admin(access.membership):
        return queryset
    role = membership_role_code(access.membership)
    if role == "manager":
        return queryset
    if role == "telecaller":
        return queryset.filter(lead__assigned_membership=access.membership)
    if role == "site-visit-executive":
        return queryset.filter(lead__site_visit__executive_membership=access.membership).distinct()
    return queryset.none()


def customer_to_dict(customer):
    return {
        "id": customer.id,
        "customer_code": customer.customer_code,
        "project_id": customer.project_id,
        "lead_id": customer.lead_id,
        "full_name": customer.full_name,
        "phone": customer.phone,
        "email": customer.email,
        "address": customer.address,
        "status": customer.status,
        "status_label": customer.get_status_display(),
        "government_id": ({"type": customer.government_id_type, "last4": customer.government_id_last4} if customer.government_id_hash else None),
        "created_at": customer.created_at.isoformat(),
        "updated_at": customer.updated_at.isoformat(),
    }


def _timeline_item(event_type, timestamp, **details):
    return {"type": event_type, "timestamp": timestamp.isoformat() if timestamp else None, **details}


def customer_360_data(customer):
    lead = customer.lead
    bookings = list(customer.bookings.select_related("plot", "project", "site_visit").all())
    total_paid = Decimal("0.00")
    outstanding = Decimal("0.00")
    for booking in bookings:
        totals = payment_totals(booking)
        total_paid += totals["net_paid"] or Decimal("0.00")
        outstanding += totals["outstanding_amount"] or Decimal("0.00")
    timeline = []
    if lead:
        timeline.append(_timeline_item("lead", lead.created_at, lead_id=lead.id, title="Lead created", status=lead.lifecycle_status))
        for item in lead.history.all():
            timeline.append(_timeline_item("lead", item.created_at, lead_id=lead.id, title=item.action, details=item.details))
        for visit in Sitevisit.objects.filter(lead=lead).all():
            timeline.append(_timeline_item("site_visit", visit.created_at, site_visit_id=visit.id, title="Site visit", status=visit.status))
        from documents.models import CustomerDocument
        for document in CustomerDocument.objects.filter(customer=customer).all():
            timeline.append(_timeline_item("document", document.created_at, document_id=document.id, title=document.document_name, status=document.status))
    for booking in bookings:
        timeline.append(_timeline_item("booking", booking.created_at, booking_id=booking.id, title="Booking", status=booking.status))
        for payment in Payment.objects.filter(booking=booking).all():
            timeline.append(_timeline_item("payment", payment.created_at, payment_id=payment.id, title="Payment", amount=str(payment.amount), status=payment.status))
    for note in customer.notes.select_related("author").all():
        timeline.append(_timeline_item("note", note.created_at, note_id=note.id, title="Customer note", note_text=note.note_text))
    timeline.sort(key=lambda item: (item["timestamp"] or "", item["type"]))
    return {
        "customer": customer_to_dict(customer),
        "totals": {"bookings_count": len(bookings), "total_paid": total_paid, "outstanding": outstanding},
        "timeline": timeline,
    }
