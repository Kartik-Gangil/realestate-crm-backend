import csv
import io
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections, transaction
from django.utils import timezone

from system_settings.master_data import validate_lead_source

from .duplicates import find_duplicates
from .models import Lead, LeadImportBatch


CSV_HEADER_ALIASES = {
    "first_name": "first_name", "firstname": "first_name", "first": "first_name",
    "last_name": "last_name", "lastname": "last_name", "last": "last_name",
    "full_name": "full_name", "fullname": "full_name", "name": "full_name",
    "email": "email", "email_address": "email", "phone": "phone", "phone_number": "phone",
    "mobile": "phone", "mobile_number": "phone", "contact_number": "phone", "source": "source",
    "platform": "source", "assigned_membership": "assigned_membership", "assigned_membership_id": "assigned_membership",
    "assignee_id": "assigned_membership",
}

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crm-lead-import")


def normalize_header(header):
    return "_".join(str(header or "").strip().lower().replace("-", " ").split())


def row_payload(row, mapping=None):
    payload = {}
    for header, value in row.items():
        field = (mapping or {}).get(header) or CSV_HEADER_ALIASES.get(normalize_header(header))
        value = str(value or "").strip()
        if field and value:
            payload[field] = value
    if "full_name" in payload:
        parts = payload.pop("full_name").split(None, 1)
        payload.setdefault("first_name", parts[0] if parts else "")
        if len(parts) == 2:
            payload.setdefault("last_name", parts[1])
    payload.setdefault("source", "website")
    return payload


def _error(row_number, message):
    return {"row": row_number, "errors": message if isinstance(message, dict) else {"detail": [str(message)]}}


def _create_lead(*, batch, payload):
    required = [field for field in ("first_name", "phone") if not payload.get(field)]
    if required:
        raise ValueError({field: "This field is required." for field in required})
    validate_lead_source(batch.organization, payload.get("source", "website"))
    lead = Lead(
        organization=batch.organization,
        project=batch.project,
        first_name=payload["first_name"],
        last_name=payload.get("last_name", ""),
        email=payload.get("email", ""),
        phone=payload["phone"],
        source=payload.get("source", "website"),
        alt_phone=payload.get("alt_phone", ""),
        address=payload.get("address", ""),
        occupation=payload.get("occupation", ""),
    )
    lead.full_clean()
    matches = find_duplicates(
        organization=batch.organization,
        payload=payload,
        queryset=Lead.all_objects.filter(organization=batch.organization, project=batch.project),
        project=batch.project,
    )
    if matches:
        raise ValueError({"duplicate": f"Possible duplicate of lead {matches[0][1].pk} ({matches[0][0]}% confidence)."})
    lead.save()
    return lead


def process_import_batch(batch_id):
    """Process rows in 500-row chunks and persist progress after each chunk."""
    close_old_connections()
    try:
        batch = LeadImportBatch.all_objects.select_related("organization", "project").get(pk=batch_id)
        batch.status = LeadImportBatch.Status.PROCESSING
        batch.save(update_fields=["status", "updated_at"])
        reader = csv.DictReader(io.StringIO(batch.raw_content))
        rows = list(reader)
        errors = []
        imported = 0
        for start in range(0, len(rows), 500):
            with transaction.atomic():
                for offset, row in enumerate(rows[start:start + 500], start=start + 2):
                    if not any(str(value or "").strip() for value in row.values()):
                        continue
                    try:
                        _create_lead(batch=batch, payload=row_payload(row, batch.field_mapping))
                        imported += 1
                    except Exception as error:
                        detail = getattr(error, "message_dict", None) or getattr(error, "messages", None) or str(error)
                        errors.append(_error(offset, detail))
            batch.imported_rows = imported
            batch.skipped_rows = len(errors)
            batch.error_report = errors
            batch.total_rows = len(rows)
            batch.save(update_fields=["total_rows", "imported_rows", "skipped_rows", "error_report", "updated_at"])
        batch.status = LeadImportBatch.Status.COMPLETED
        batch.save(update_fields=["status", "updated_at"])
        return batch
    except Exception as error:
        batch = LeadImportBatch.all_objects.filter(pk=batch_id).first()
        if batch:
            batch.status = LeadImportBatch.Status.FAILED
            batch.error_report = [_error(0, str(error))]
            batch.save(update_fields=["status", "error_report", "updated_at"])
        raise
    finally:
        close_old_connections()


def enqueue_lead_import(batch_id):
    """NFR-P4-01: enqueue work outside the request thread."""
    return _executor.submit(process_import_batch, batch_id)
