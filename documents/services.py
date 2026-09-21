from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.core.files.base import ContentFile
from django.utils.dateparse import parse_datetime
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import (CustomerDocument, CustomerDocumentRequirement, CustomerDocumentVerificationHistory,
                     DocumentExpiryNotification, EmployeeDocument, EkycVerification)
from .security import encrypt_bytes, encrypt_text


def _validate_file(uploaded_file):
    maximum = getattr(settings, "DOCUMENT_MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    allowed = {"application/pdf", "image/jpeg", "image/png"}
    if not uploaded_file:
        raise ValidationError({"file": "A document file is required."})
    if uploaded_file.size > maximum:
        raise ValidationError({"file": f"File must not exceed {maximum} bytes."})
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    header = uploaded_file.read(12); uploaded_file.seek(0)
    signatures = {"application/pdf": header.startswith(b"%PDF"), "image/jpeg": header.startswith(b"\xff\xd8\xff"), "image/png": header.startswith(b"\x89PNG\r\n\x1a\n")}
    if content_type not in allowed or not signatures.get(content_type):
        raise ValidationError({"file": "Upload a valid PDF, JPG, JPEG, or PNG file."})


def upload_customer_document(*, organization, customer, document_category, uploaded_file, document_name, expiry_date=None, notes="", user=None):
    if customer.organization_id != organization.id or document_category.organization_id != organization.id:
        raise ValidationError("Customer and category must belong to this organization.")
    if not document_category.is_active:
        raise ValidationError({"document_category": "This document category is inactive."})
    _validate_file(uploaded_file)
    original_size = uploaded_file.size
    encrypted_file = ContentFile(encrypt_bytes(uploaded_file.read()), name=uploaded_file.name + ".enc")
    with transaction.atomic():
        active = CustomerDocument.objects.select_for_update().filter(organization=organization, customer=customer, document_category=document_category, is_active=True)
        active.update(is_active=False, archived_at=timezone.now())
        latest = CustomerDocument.objects.select_for_update().filter(organization=organization, customer=customer, document_category=document_category).order_by("-version").first()
        document = CustomerDocument.objects.create(organization=organization, customer=customer, document_category=document_category, document_name=document_name.strip(), file=encrypted_file, file_name=uploaded_file.name, file_size=original_size, content_type=uploaded_file.content_type, version=(latest.version + 1 if latest else 1), expiry_date=expiry_date, notes=notes or "", uploaded_by=user)
        CustomerDocumentVerificationHistory.objects.create(document=document, old_status=CustomerDocument.Status.UPLOADED, new_status=CustomerDocument.Status.UPLOADED, reason="Document uploaded", changed_by=user)
        return document


def archive_customer_document(*, document, user=None):
    with transaction.atomic():
        document = CustomerDocument.objects.select_for_update().get(pk=document.pk)
        if not document.is_active:
            raise ValidationError({"document": "Document is already archived."})
        document.is_active = False; document.archived_at = timezone.now(); document.save(update_fields=["is_active", "archived_at", "updated_at"])
        return document


TRANSITIONS = {CustomerDocument.Status.UPLOADED: {CustomerDocument.Status.UNDER_VERIFICATION}, CustomerDocument.Status.UNDER_VERIFICATION: {CustomerDocument.Status.VERIFIED, CustomerDocument.Status.REJECTED}}


def _transition(*, document, new_status, user, reason=""):
    with transaction.atomic():
        document = CustomerDocument.objects.select_for_update().get(pk=document.pk)
        if not document.is_active:
            raise ValidationError({"document": "Only the active document version can be reviewed."})
        if new_status not in TRANSITIONS.get(document.status, set()):
            raise ValidationError({"status": f"Cannot change document from '{document.status}' to '{new_status}'."})
        if new_status == CustomerDocument.Status.REJECTED and not reason.strip():
            raise ValidationError({"rejection_reason": "A rejection reason is required."})
        old = document.status; document.status = new_status
        fields = ["status", "updated_at"]
        now = timezone.now()
        if new_status == CustomerDocument.Status.VERIFIED:
            document.verified_by = user; document.verified_at = now; document.rejected_by = None; document.rejected_at = None; document.rejection_reason = ""; fields += ["verified_by", "verified_at", "rejected_by", "rejected_at", "rejection_reason"]
        if new_status == CustomerDocument.Status.REJECTED:
            document.rejected_by = user; document.rejected_at = now; document.rejection_reason = reason.strip(); fields += ["rejected_by", "rejected_at", "rejection_reason"]
        document.save(update_fields=fields)
        CustomerDocumentVerificationHistory.objects.create(document=document, old_status=old, new_status=new_status, reason=reason.strip(), changed_by=user)
        return document


def put_document_under_verification(*, document, user): return _transition(document=document, new_status=CustomerDocument.Status.UNDER_VERIFICATION, user=user)
def verify_customer_document(*, document, user): return _transition(document=document, new_status=CustomerDocument.Status.VERIFIED, user=user)
def reject_customer_document(*, document, user, reason): return _transition(document=document, new_status=CustomerDocument.Status.REJECTED, user=user, reason=reason)


def get_customer_document_summary(customer):
    today = timezone.localdate(); warning = today + timedelta(days=getattr(settings, "DOCUMENT_EXPIRY_WARNING_DAYS", 30))
    docs = CustomerDocument.objects.filter(customer=customer, is_active=True)
    counts = docs.aggregate(total_documents=Count("id"), verified_documents=Count("id", filter=Q(status=CustomerDocument.Status.VERIFIED, expiry_date__isnull=True) | Q(status=CustomerDocument.Status.VERIFIED, expiry_date__gte=today)), pending_documents=Count("id", filter=Q(status__in=[CustomerDocument.Status.UPLOADED, CustomerDocument.Status.UNDER_VERIFICATION])), rejected_documents=Count("id", filter=Q(status=CustomerDocument.Status.REJECTED)), expired_documents=Count("id", filter=Q(expiry_date__lt=today) | Q(status=CustomerDocument.Status.EXPIRED)), expiring_soon_documents=Count("id", filter=Q(expiry_date__gte=today, expiry_date__lte=warning)))
    requirements = CustomerDocumentRequirement.objects.filter(customer=customer, is_mandatory=True, is_active=True)
    active_categories = set(docs.values_list("document_category_id", flat=True))
    counts["mandatory_documents"] = requirements.count(); counts["missing_mandatory_documents"] = requirements.exclude(document_category_id__in=active_categories).count()
    return counts


def validate_customer_documents_for_booking(customer):
    """Evaluate only current versions; row locks make a booking decision race-safe."""
    today = timezone.localdate(); requirements = CustomerDocumentRequirement.objects.select_for_update().filter(customer=customer, is_mandatory=True, is_active=True).select_related("document_category")
    active = {d.document_category_id: d for d in CustomerDocument.objects.select_for_update().filter(customer=customer, is_active=True).select_related("document_category")}
    result = {"allowed": True, "missing": [], "pending": [], "rejected": [], "expired": []}
    for req in requirements:
        doc = active.get(req.document_category_id); label = req.document_category.name
        if not doc: result["missing"].append(label)
        elif doc.status in {CustomerDocument.Status.UPLOADED, CustomerDocument.Status.UNDER_VERIFICATION}: result["pending"].append(label)
        elif doc.status == CustomerDocument.Status.REJECTED: result["rejected"].append(label)
        elif doc.status != CustomerDocument.Status.VERIFIED or (doc.expiry_date and doc.expiry_date < today): result["expired"].append(label)
    result["allowed"] = not any(result[key] for key in ("missing", "pending", "rejected", "expired"))
    return result


def _mock_ekyc_result(checks):
    if checks.get("simulate_outage"):
        return "pending", {}, "Provider unavailable"
    try:
        face = Decimal(str(checks.get("face_match", 0)))
    except (InvalidOperation, TypeError):
        face = Decimal("0")
    passed = bool(checks.get("aadhaar")) and bool(checks.get("pan")) and face >= Decimal("0.80")
    return ("verified", {"provider": "mock", "checks": {"aadhaar": bool(checks.get("aadhaar")), "pan": bool(checks.get("pan")), "face_match": str(face)}}, "") if passed else ("failed", {"provider": "mock"}, "Identity checks did not pass")


def _run_ekyc(verification, checks):
    result, payload, error = _mock_ekyc_result(checks)
    verification.verification_status = result
    verification.response_payload = payload
    verification.last_error = error
    verification.next_retry_at = timezone.now() + timedelta(minutes=5) if result == EkycVerification.Status.PENDING else None
    if result == EkycVerification.Status.VERIFIED:
        verification.verified_at = timezone.now()
        verification.customer.ekyc_status = verification.customer.EkycStatus.VERIFIED
        verification.customer.save(update_fields=["ekyc_status", "updated_at"])
    verification.save(update_fields=["verification_status", "response_payload", "last_error", "next_retry_at", "verified_at", "updated_at"])
    return verification


def verify_ekyc(*, customer, provider="mock", id_number="", checks=None, actor=None):
    checks = checks or {}
    if customer.ekyc_verifications.filter(verification_status=EkycVerification.Status.PENDING).exists():
        raise ValidationError({"ekyc": "An eKYC verification is already pending."})
    verification = EkycVerification.objects.create(organization=customer.organization, customer=customer, provider=provider, id_number_encrypted=encrypt_text(id_number) if id_number else "", attempts=1, requested_by=actor)
    return _run_ekyc(verification, checks)


def process_ekyc_retry(*, verification, actor=None, checks=None):
    verification.attempts += 1
    verification.requested_by = actor or verification.requested_by
    verification.save(update_fields=["attempts", "requested_by", "updated_at"])
    return _run_ekyc(verification, checks or {})


def is_customer_ekyc_verified(customer):
    return customer.ekyc_status == customer.EkycStatus.VERIFIED or customer.ekyc_verifications.filter(verification_status=EkycVerification.Status.VERIFIED).exists()


def create_expiry_notifications(*, now=None):
    today = now or timezone.localdate()
    warning = today + timedelta(days=getattr(settings, "DOCUMENT_EXPIRY_WARNING_DAYS", 30))
    documents = CustomerDocument.objects.filter(is_active=True, expiry_date__gte=today, expiry_date__lte=warning).select_related("customer", "organization")
    created = 0
    for document in documents:
        recipient = document.customer.email or document.customer.phone
        if not recipient:
            continue
        channel = DocumentExpiryNotification.Channel.EMAIL if document.customer.email else DocumentExpiryNotification.Channel.SMS
        _, was_created = DocumentExpiryNotification.objects.get_or_create(document=document, channel=channel, alert_date=today, defaults={"organization": document.organization, "recipient": recipient, "scheduled_for": timezone.now()})
        created += int(was_created)
    return created


def upload_employee_document(*, organization, employee, document_category, uploaded_file, document_name, expiry_date=None, user=None):
    if employee.organization_id != organization.id or document_category.organization_id != organization.id:
        raise ValidationError("Employee and category must belong to this organization.")
    if not document_category.is_active:
        raise ValidationError({"document_category": "This document category is inactive."})
    _validate_file(uploaded_file)
    with transaction.atomic():
        active = EmployeeDocument.objects.select_for_update().filter(organization=organization, employee=employee, document_category=document_category, is_active=True)
        active.update(is_active=False, status=EmployeeDocument.Status.ARCHIVED, archived_at=timezone.now())
        latest = EmployeeDocument.objects.select_for_update().filter(organization=organization, employee=employee, document_category=document_category).order_by("-version").first()
        return EmployeeDocument.objects.create(organization=organization, employee=employee, document_category=document_category,
                                               document_name=document_name.strip(), file=uploaded_file, file_name=uploaded_file.name,
                                               file_size=uploaded_file.size, content_type=uploaded_file.content_type,
                                               version=(latest.version + 1 if latest else 1), expiry_date=expiry_date, uploaded_by=user)


def archive_employee_document(*, document):
    with transaction.atomic():
        document = EmployeeDocument.objects.select_for_update().get(pk=document.pk)
        if not document.is_active:
            raise ValidationError({"document": "Document is already archived."})
        document.is_active = False
        document.status = EmployeeDocument.Status.ARCHIVED
        document.archived_at = timezone.now()
        document.save(update_fields=["is_active", "status", "archived_at", "updated_at"])
        return document
