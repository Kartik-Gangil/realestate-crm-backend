from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.files import DOCUMENT_KINDS, validate_upload
from .models import (CustomerDocument, CustomerDocumentRequirement, CustomerDocumentVerificationHistory,
                     EmployeeDocument)
from system_settings.audit import log_bulk_audit


def _validate_file(uploaded_file):
    maximum = getattr(settings, "DOCUMENT_MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    return validate_upload(uploaded_file, kinds=DOCUMENT_KINDS, max_bytes=maximum)


def upload_customer_document(*, organization, customer, document_category, uploaded_file, document_name, expiry_date=None, notes="", user=None, request=None):
    if customer.organization_id != organization.id or document_category.organization_id != organization.id:
        raise ValidationError("Customer and category must belong to this organization.")
    if not document_category.is_active:
        raise ValidationError({"document_category": "This document category is inactive."})
    content_type = _validate_file(uploaded_file)
    with transaction.atomic():
        active = CustomerDocument.objects.select_for_update().filter(organization=organization, customer=customer, document_category=document_category, is_active=True)
        active_items = list(active)
        active.update(is_active=False, archived_at=timezone.now())
        if active_items:
            log_bulk_audit(request=request, module="documents", action="bulk_update", instances=active_items, organization=organization,
                           changed_values={"is_active": False, "archived_at": "now"})
        latest = CustomerDocument.objects.select_for_update().filter(organization=organization, customer=customer, document_category=document_category).order_by("-version").first()
        document = CustomerDocument.objects.create(organization=organization, customer=customer, document_category=document_category, document_name=document_name.strip(), file=uploaded_file, file_name=uploaded_file.name, file_size=uploaded_file.size, content_type=content_type, version=(latest.version + 1 if latest else 1), expiry_date=expiry_date, notes=notes or "", uploaded_by=user)
        CustomerDocumentVerificationHistory.objects.create(document=document, old_status=CustomerDocument.Status.UPLOADED, new_status=CustomerDocument.Status.UPLOADED, reason="Document uploaded", changed_by=user)
        return document


def archive_customer_document(*, document, user=None, request=None):
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

    def is_identity_category(category):
        value = f"{category.code} {category.name}".lower().replace("_", "-")
        return any(token in value for token in ("identity", "id-proof", "aadhaar", "aadhar", "pan"))

    identity_documents = [document for document in active.values() if is_identity_category(document.document_category)]
    if not any(
        document.status == CustomerDocument.Status.VERIFIED
        and (document.expiry_date is None or document.expiry_date >= today)
        for document in identity_documents
    ):
        if not identity_documents:
            result["missing"].append("Identity document")
        else:
            document = identity_documents[0]
            label = document.document_category.name
            if document.status in {CustomerDocument.Status.UPLOADED, CustomerDocument.Status.UNDER_VERIFICATION}:
                if label not in result["pending"]:
                    result["pending"].append(label)
            elif document.status == CustomerDocument.Status.REJECTED:
                if label not in result["rejected"]:
                    result["rejected"].append(label)
            else:
                if label not in result["expired"]:
                    result["expired"].append(label)
    result["allowed"] = not any(result[key] for key in ("missing", "pending", "rejected", "expired"))
    return result


def upload_employee_document(*, organization, employee, document_category, uploaded_file, document_name, expiry_date=None, user=None):
    if employee.organization_id != organization.id or document_category.organization_id != organization.id:
        raise ValidationError("Employee and category must belong to this organization.")
    if not document_category.is_active:
        raise ValidationError({"document_category": "This document category is inactive."})
    content_type = _validate_file(uploaded_file)
    with transaction.atomic():
        active = EmployeeDocument.objects.select_for_update().filter(organization=organization, employee=employee, document_category=document_category, is_active=True)
        active_items = list(active)
        active.update(is_active=False, status=EmployeeDocument.Status.ARCHIVED, archived_at=timezone.now())
        if active_items:
            log_bulk_audit(module="documents", action="bulk_update", instances=active_items, organization=organization,
                           changed_values={"is_active": False, "status": EmployeeDocument.Status.ARCHIVED, "archived_at": "now"})
        latest = EmployeeDocument.objects.select_for_update().filter(organization=organization, employee=employee, document_category=document_category).order_by("-version").first()
        return EmployeeDocument.objects.create(organization=organization, employee=employee, document_category=document_category,
                                               document_name=document_name.strip(), file=uploaded_file, file_name=uploaded_file.name,
                                               file_size=uploaded_file.size, content_type=content_type,
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
