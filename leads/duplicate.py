from django.core.exceptions import ValidationError
from django.db.models import Q

from system_settings.services import get_system_parameter

from .models import Lead
from .phone import normalize_phone


RULE_PARAMETERS = (
    ("phone_exact", "duplicate_score_phone_exact"),
    ("phone_different_name", "duplicate_score_phone_different_name"),
    ("email_partial_phone", "duplicate_score_email_partial_phone"),
)


def _full_name(payload):
    if payload.get("full_name") is not None:
        return str(payload.get("full_name") or "").strip()
    return " ".join(
        part for part in (
            str(payload.get("first_name") or "").strip(),
            str(payload.get("last_name") or "").strip(),
        ) if part
    )


def score_duplicates(organization, project, payload, *, exclude_lead_id=None):
    raw_phone = payload.get("phone")
    phone = normalize_phone(raw_phone) if raw_phone else None
    if raw_phone and phone is None:
        raise ValidationError({"phone": "Phone number cannot be normalized."})
    email = str(payload.get("email") or "").strip().casefold()
    name = _full_name(payload).casefold()
    if not phone and not email:
        return []

    scores = {
        rule: get_system_parameter(organization, parameter_key, project=project)
        for rule, parameter_key in RULE_PARAMETERS
    }
    candidate_filter = Q()
    if phone:
        candidate_filter |= Q(phone=phone)
    if email:
        candidate_filter |= Q(email__iexact=email)
    queryset = Lead.objects.filter(
        Q(organization=organization) & Q(project=project) & candidate_filter
    ).order_by("id")
    if exclude_lead_id is not None:
        queryset = queryset.exclude(pk=exclude_lead_id)

    matches = []
    for lead in queryset:
        existing_phone = normalize_phone(lead.phone)
        existing_name = lead.full_name.strip().casefold()
        existing_email = (lead.email or "").strip().casefold()
        candidates = []
        if phone and existing_phone and phone == existing_phone:
            candidates.append((scores["phone_exact"] if name == existing_name else scores["phone_different_name"], "phone_exact" if name == existing_name else "phone_different_name"))
        if email and existing_email and email == existing_email and phone and existing_phone and phone[-7:] == existing_phone[-7:]:
            candidates.append((scores["email_partial_phone"], "email_partial_phone"))
        if not candidates:
            continue
        score, rule = max(candidates, key=lambda item: item[0])
        matches.append({
            "id": lead.id,
            "name": lead.full_name,
            "full_name": lead.full_name,
            "phone": lead.phone,
            "email": lead.email,
            "lead_code": lead.lead_code,
            "score": score,
            "confidence": score,
            "rule": rule,
        })
    return matches
