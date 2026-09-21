from django.core.exceptions import ValidationError
from django.db import transaction

from .models import RegistryDocument


def attach_document_to_registry(*, registry, customer_document_id=None, uploaded_file=None,
                                 document_label="", document_type="", user=None):
    from documents.models import CustomerDocument
    from documents.services import _validate_file

    if customer_document_id and uploaded_file:
        raise ValidationError({"detail": "Provide either a customer_document_id or a file, not both."})
    if not customer_document_id and not uploaded_file:
        raise ValidationError({"detail": "Provide either a customer_document_id or a file upload."})

    with transaction.atomic():
        if customer_document_id:
            doc = CustomerDocument.objects.filter(
                pk=customer_document_id, organization=registry.organization,
                customer=registry.booking.lead, is_active=True,
            ).first()
            if not doc:
                raise ValidationError({"customer_document_id": "Active eKYC document not found for this customer."})
            registry_doc = RegistryDocument.objects.create(
                registry=registry, organization=registry.organization,
                customer_document=doc,
                document_label=document_label or doc.document_name,
                document_type=document_type or "ekyc",
                uploaded_by=user,
            )
        else:
            _validate_file(uploaded_file)
            registry_doc = RegistryDocument.objects.create(
                registry=registry, organization=registry.organization,
                file=uploaded_file, file_name=uploaded_file.name,
                file_size=uploaded_file.size, content_type=uploaded_file.content_type,
                document_label=document_label or uploaded_file.name,
                document_type=document_type or "other",
                uploaded_by=user,
            )
        return registry_doc


def remove_registry_document(*, registry_document, user=None):
    with transaction.atomic():
        rd = RegistryDocument.objects.select_for_update().get(pk=registry_document.pk)
        if rd.file:
            rd.file.delete(save=False)
        rd.delete()
        return True
