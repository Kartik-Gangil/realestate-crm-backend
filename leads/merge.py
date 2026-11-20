from django.core.exceptions import ValidationError

from system_settings.audit import log_bulk_audit

from .models import LeadHistory
from .phone import normalize_phone


MERGE_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "alt_phone",
    "address",
    "occupation",
    "source",
    "source_item_id",
    "status_id",
    "score",
    "budget_range",
    "preferred_location",
    "external_source",
    "external_id",
    "assigned_membership_id",
)


def merge_into_existing(*, existing, payload, request=None):
    candidate = dict(payload)
    if candidate.get("phone"):
        candidate["phone"] = normalize_phone(candidate["phone"])
        if candidate["phone"] is None:
            raise ValidationError({"phone": "Phone number cannot be normalized."})
    if candidate.get("alt_phone"):
        candidate["alt_phone"] = normalize_phone(candidate["alt_phone"])
        if candidate["alt_phone"] is None:
            raise ValidationError({"alt_phone": "Phone number cannot be normalized."})

    before_fields = {field: getattr(existing, field, None) for field in MERGE_FIELDS}
    fields_filled = []
    for field in MERGE_FIELDS:
        value = candidate.get(field)
        if getattr(existing, field, None) in (None, "", 0) and value not in (None, ""):
            setattr(existing, field, value)
            fields_filled.append(field)
    if fields_filled:
        existing.save(update_fields=sorted(set(fields_filled + ["updated_at"])))

    details = {"fields_filled": fields_filled, "creates_new_lead": False}
    LeadHistory.objects.create(
        lead=existing,
        organization=existing.organization,
        project=existing.project,
        action="merge",
        details=details,
        created_by=request.user if request and request.user.is_authenticated else None,
    )
    log_bulk_audit(
        request=request,
        organization=existing.organization,
        project=existing.project,
        module="leads",
        action="merge",
        instances=[existing],
        before={"fields": sorted(before_fields)},
        after=details,
        changed_values=details,
    )
    return existing
