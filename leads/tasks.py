import csv
import io

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.tasks import task

from .duplicate import score_duplicates
from .constants import LEAD_STATUS_NEW
from .models import Lead, LeadImportBatch
from .phone import normalize_phone
from .codes import allocate_lead_codes
from .views import _csv_row_payload
from system_settings.audit import log_bulk_audit
from system_settings.models import MasterData


CHUNK_SIZE = 500


def _rows_for_batch(batch):
    with batch.upload.storage.open(batch.upload.name, "rb") as source:
        content = source.read()
    if batch.file_name.lower().endswith(".csv"):
        return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    import pandas as pd
    frame = pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl" if batch.file_name.lower().endswith(".xlsx") else "xlrd")
    return frame.fillna("").to_dict(orient="records")


def _write_error_report(batch):
    if not batch.error_rows:
        return
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["row_number", "reason", "original_values"])
    writer.writeheader()
    writer.writerows(batch.error_rows)
    batch.error_report.save(
        f"lead-import-{batch.pk}-errors.csv",
        ContentFile(output.getvalue().encode("utf-8")),
        save=False,
    )


@task
def process_lead_import(batch_id):
    batch = LeadImportBatch.objects.select_related("organization", "project", "created_by").get(pk=batch_id)
    batch.status = LeadImportBatch.Status.RUNNING
    batch.save(update_fields=["status", "updated_at"])
    rows = _rows_for_batch(batch)
    batch.total_rows = len(rows)
    batch.save(update_fields=["total_rows", "updated_at"])
    existing_phones = set(Lead.objects.filter(project=batch.project).values_list("phone", flat=True))
    existing_emails = {value.strip().casefold() for value in Lead.objects.filter(project=batch.project).exclude(email="").values_list("email", flat=True)}
    new_stage_id = MasterData.objects.filter(
        organization_id=batch.organization_id,
        project_id=batch.project_id,
        category__code="lead_stage",
        code=LEAD_STATUS_NEW,
        is_active=True,
    ).values_list("id", flat=True).first()
    start = batch.current_chunk * CHUNK_SIZE
    for chunk_start in range(start, len(rows), CHUNK_SIZE):
        chunk = rows[chunk_start:chunk_start + CHUNK_SIZE]
        with transaction.atomic():
            imported = 0
            skipped = 0
            errors = list(batch.error_rows)
            new_leads = []
            for offset, row in enumerate(chunk):
                row_number = chunk_start + offset + 2
                original_values = {str(key): str(value or "") for key, value in row.items() if key is not None}
                try:
                    payload = _csv_row_payload(row)
                    if not payload.get("first_name") or not payload.get("phone"):
                        raise ValidationError("Required first_name and phone are missing.")
                    normalized_phone = normalize_phone(payload.get("phone"))
                    normalized_email = str(payload.get("email") or "").strip().casefold()
                    matches = []
                    if normalized_phone in existing_phones or normalized_email in existing_emails:
                        matches = score_duplicates(batch.organization, batch.project, payload)
                    if matches and not batch.import_duplicates:
                        skipped += 1
                        errors.append({"row_number": row_number, "reason": "duplicate lead", "original_values": str(original_values)})
                        continue
                    lead = Lead(project=batch.project)
                    from .views import _apply_payload
                    _apply_payload(lead, payload, batch.organization, save=False, project=batch.project)
                    lead.status_id = new_stage_id
                    new_leads.append(lead)
                except (ValidationError, ValueError, TypeError) as error:
                    skipped += 1
                    reason = str(error.message_dict if hasattr(error, "message_dict") else error)
                    errors.append({"row_number": row_number, "reason": reason, "original_values": str(original_values)})
            if new_leads:
                for lead, lead_code in zip(new_leads, allocate_lead_codes(batch.project, len(new_leads))):
                    lead.lead_code = lead_code
                Lead.objects.bulk_create(new_leads)
                log_bulk_audit(
                    module="leads",
                    action="bulk_create",
                    instances=new_leads,
                    organization=batch.organization,
                    project=batch.project,
                    user=batch.created_by,
                    changed_values={"fields": ["first_name", "phone", "source"]},
                    route="task:process_lead_import",
                )
                for lead in new_leads:
                    existing_phones.add(lead.phone)
                    if lead.email:
                        existing_emails.add(lead.email.strip().casefold())
                imported = len(new_leads)
            batch.imported_rows += imported
            batch.skipped_rows += skipped
            batch.error_rows = errors
            batch.current_chunk = chunk_start // CHUNK_SIZE + 1
            batch.save(update_fields=["imported_rows", "skipped_rows", "error_rows", "current_chunk", "updated_at"])
    batch.status = LeadImportBatch.Status.COMPLETED
    _write_error_report(batch)
    batch.save(update_fields=["status", "error_report", "updated_at"])
    return {"batch_id": batch.pk, "imported_rows": batch.imported_rows, "skipped_rows": batch.skipped_rows}
