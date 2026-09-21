from django.core.exceptions import ValidationError

from .models import MasterData


CALL_DISPOSITION_MASTER_TYPE = "call_disposition"
CALL_DISPOSITION_DEFINITIONS = (
    ("interested", "Interested"),
    ("callback_later", "Callback Later"),
    ("busy", "Busy"),
    ("no_answer", "No Answer"),
    ("switched_off", "Switched Off"),
    ("wrong_number", "Wrong Number"),
    ("dnd", "DND"),
    ("already_purchased", "Already Purchased"),
)
CALL_DISPOSITION_CODES = tuple(code for code, _name in CALL_DISPOSITION_DEFINITIONS)
CONNECTED_CALL_DISPOSITION_CODES = ("interested", "callback_later", "already_purchased")
FOLLOW_UP_REQUIRED_DISPOSITION_CODES = ("interested", "callback_later")

LEAD_SOURCE_MASTER_TYPE = "lead_source"
LEAD_SOURCE_DEFINITIONS = (
    ("fb", "Facebook"),
    ("ig", "Instagram"),
    ("website", "Website"),
    ("site_visit", "Site Visit"),
    ("other", "Other"),
    ("walk_in", "Walk-in"),
)

SITE_VISIT_OUTCOME_MASTER_TYPE = "site_visit_outcome"
SITE_VISIT_OUTCOME_DEFINITIONS = (
    ("interested", "Interested"),
    ("need_more_time", "Need More Time"),
    ("price_issue", "Price Issue"),
    ("location_issue", "Location Issue"),
    ("loan_issue", "Loan Issue"),
    ("already_purchased", "Already Purchased"),
    ("wrong_requirement", "Wrong Requirement"),
)

PLOT_STATUS_MASTER_TYPE = "plot_status"
PLOT_STATUS_DEFINITIONS = (
    ("available", "Available"),
    ("blocked", "Blocked"),
    ("hold", "Hold"),
    ("booked", "Booked"),
    ("sold", "Sold"),
    ("cancelled", "Cancelled"),
    ("under_construction", "Under Construction"),
)

LEAD_STATUS_MASTER_TYPE = "lead_status"
LEAD_STATUS_DEFINITIONS = (
    ("new", "New"),
    ("contacted", "Contacted"),
    ("interested", "Interested"),
    ("site_visit_scheduled", "Site Visit Scheduled"),
    ("site_visit_completed", "Site Visit Completed"),
    ("converted", "Converted"),
    ("lost", "Lost"),
)


def ensure_call_dispositions(organization):
    """Provision the fixed FR-P6-03 catalogue without reactivating disabled items."""
    for sort_order, (code, name) in enumerate(CALL_DISPOSITION_DEFINITIONS, start=1):
        disposition, _created = MasterData.objects.get_or_create(
            organization=organization,
            master_type=CALL_DISPOSITION_MASTER_TYPE,
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_system": True},
        )
        if not disposition.is_system:
            disposition.is_system = True
            disposition.save(update_fields=["is_system"])
    return MasterData.objects.filter(
        organization=organization,
        master_type=CALL_DISPOSITION_MASTER_TYPE,
        code__in=CALL_DISPOSITION_CODES,
    ).order_by("sort_order", "id")


def active_call_dispositions(organization):
    ensure_call_dispositions(organization)
    return MasterData.objects.filter(
        organization=organization,
        master_type=CALL_DISPOSITION_MASTER_TYPE,
        code__in=CALL_DISPOSITION_CODES,
        is_active=True,
    ).order_by("sort_order", "id")


def validate_call_disposition(organization, code):
    ensure_call_dispositions(organization)
    disposition = MasterData.objects.filter(
        organization=organization,
        master_type=CALL_DISPOSITION_MASTER_TYPE,
        code=code,
        code__in=CALL_DISPOSITION_CODES,
        is_active=True,
    ).first()
    if disposition is None:
        raise ValidationError({"disposition": "Select an active call disposition."})
    return disposition


def ensure_lead_sources(organization):
    """FR-P2-01/GNFR-09: provision protected defaults for the current project."""
    for sort_order, (code, name) in enumerate(LEAD_SOURCE_DEFINITIONS, start=1):
        source, _created = MasterData.objects.get_or_create(
            organization=organization,
            master_type=LEAD_SOURCE_MASTER_TYPE,
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_system": True},
        )
        if not source.is_system:
            source.is_system = True
            source.save(update_fields=["is_system"])
    return MasterData.objects.filter(
        organization=organization,
        master_type=LEAD_SOURCE_MASTER_TYPE,
    ).order_by("sort_order", "id")


def validate_lead_source(organization, code):
    ensure_lead_sources(organization)
    source = MasterData.objects.filter(
        organization=organization,
        master_type=LEAD_SOURCE_MASTER_TYPE,
        code=code,
        is_active=True,
    ).first()
    if source is None:
        raise ValidationError({"source": "Select an active lead source."})
    return source


def ensure_site_visit_outcomes(organization):
    """FR-P2-01/FR-P7-04: provision protected outcomes for the current project."""
    for sort_order, (code, name) in enumerate(SITE_VISIT_OUTCOME_DEFINITIONS, start=1):
        outcome, _created = MasterData.objects.get_or_create(
            organization=organization,
            master_type=SITE_VISIT_OUTCOME_MASTER_TYPE,
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_system": True},
        )
        if not outcome.is_system:
            outcome.is_system = True
            outcome.save(update_fields=["is_system"])
    return MasterData.objects.filter(
        organization=organization,
        master_type=SITE_VISIT_OUTCOME_MASTER_TYPE,
    ).order_by("sort_order", "id")


def validate_site_visit_outcome(organization, code):
    ensure_site_visit_outcomes(organization)
    outcome = MasterData.objects.filter(
        organization=organization,
        master_type=SITE_VISIT_OUTCOME_MASTER_TYPE,
        code=code,
        is_active=True,
    ).first()
    if outcome is None:
        raise ValidationError({"outcome": "Select an active site-visit outcome."})
    return outcome


def ensure_plot_statuses(organization):
    """FR-P2-01/03 and FR-P8-02: provision the confirmed protected status set."""
    for sort_order, (code, name) in enumerate(PLOT_STATUS_DEFINITIONS, start=1):
        plot_status, _created = MasterData.objects.get_or_create(
            organization=organization,
            master_type=PLOT_STATUS_MASTER_TYPE,
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_system": True},
        )
        if not plot_status.is_system:
            plot_status.is_system = True
            plot_status.save(update_fields=["is_system"])
    return MasterData.objects.filter(
        organization=organization,
        master_type=PLOT_STATUS_MASTER_TYPE,
    ).order_by("sort_order", "id")


def validate_plot_status(organization, code):
    ensure_plot_statuses(organization)
    plot_status = MasterData.objects.filter(
        organization=organization,
        master_type=PLOT_STATUS_MASTER_TYPE,
        code=code,
        is_active=True,
    ).first()
    if plot_status is None:
        raise ValidationError({"status": "Select an active plot status."})
    return plot_status


def ensure_lead_statuses(organization):
    """FR-P2-01/FR-P5-02: provision the protected lead lifecycle catalogue."""
    for sort_order, (code, name) in enumerate(LEAD_STATUS_DEFINITIONS, start=1):
        lead_status, _created = MasterData.objects.get_or_create(
            organization=organization,
            master_type=LEAD_STATUS_MASTER_TYPE,
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_system": True},
        )
        if not lead_status.is_system:
            lead_status.is_system = True
            lead_status.save(update_fields=["is_system"])
    return MasterData.objects.filter(
        organization=organization,
        master_type=LEAD_STATUS_MASTER_TYPE,
    ).order_by("sort_order", "id")
