import re

from system_settings.services import get_system_parameter


def normalize_phone(value):
    """NFR-P4-02: normalize phone values before duplicate comparison."""
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits[-10:] if len(digits) > 10 else digits


def normalize_name(value):
    return " ".join(str(value or "").lower().split())


def _candidate_name(payload):
    return normalize_name(payload.get("full_name") or " ".join(
        part for part in (payload.get("first_name", ""), payload.get("last_name", "")) if part
    ))


def _partial_phone(left, right):
    left, right = normalize_phone(left), normalize_phone(right)
    return bool(left and right and (left.endswith(right) or right.endswith(left)))


def duplicate_score(payload, existing, *, thresholds=None):
    """FR-P4-04: return the exact configured confidence score for one match."""
    thresholds = thresholds or {}
    phone_exact = thresholds.get("phone_exact", 95)
    phone_name_mismatch = thresholds.get("phone_name_mismatch", 90)
    email_partial_phone = thresholds.get("email_partial_phone", 80)
    incoming_phone = normalize_phone(payload.get("phone"))
    existing_phone = normalize_phone(existing.phone)
    incoming_email = str(payload.get("email", "")).strip().lower()
    existing_email = str(existing.email or "").strip().lower()
    if incoming_phone and existing_phone and incoming_phone == existing_phone:
        return phone_name_mismatch if _candidate_name(payload) and _candidate_name(payload) != normalize_name(existing.full_name) else phone_exact
    if incoming_email and existing_email and incoming_email == existing_email and _partial_phone(incoming_phone, existing_phone):
        return email_partial_phone
    return 0


def duplicate_thresholds(organization, *, project=None):
    """Read duplicate weights from Phase 2 system parameters with spec defaults."""
    return {
        "phone_exact": get_system_parameter(organization, "lead_duplicate_phone_exact_confidence", 95, project=project),
        "phone_name_mismatch": get_system_parameter(organization, "lead_duplicate_phone_name_mismatch_confidence", 90, project=project),
        "email_partial_phone": get_system_parameter(organization, "lead_duplicate_email_partial_phone_confidence", 80, project=project),
        "warning_threshold": get_system_parameter(organization, "lead_duplicate_warning_threshold", 80, project=project),
    }


def find_duplicates(*, organization, payload, queryset, project=None):
    thresholds = duplicate_thresholds(organization, project=project)
    matches = []
    for lead in queryset:
        confidence = duplicate_score(payload, lead, thresholds=thresholds)
        if confidence >= thresholds["warning_threshold"]:
            matches.append((confidence, lead))
    return sorted(matches, key=lambda item: (-item[0], item[1].pk))
