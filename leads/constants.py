"""Canonical lead lifecycle and source keys."""

LEAD_STATUS_CODES = (
    "new",
    "contacted",
    "qualified",
    "site_visit",
    "negotiation",
    "won",
    "lost",
)

CANONICAL_LEAD_STATUS_CODES = (
    "new", "contacted", "interested", "site_visit_scheduled",
    "site_visit_completed", "converted", "lost",
)

LEAD_STATUS_ORDER = (
    "new", "contacted", "interested", "site_visit_scheduled",
    "site_visit_completed", "converted",
)

LEAD_SOURCE_CODES = (
    "fb",
    "ig",
    "website",
    "site_visit",
    "walk_in",
    "other",
    "google",
)

LEAD_STATUS_NEW = "new"

LEAD_STATUS_LABELS = {
    "new": "New",
    "contacted": "Contacted",
    "interested": "Interested",
    "site_visit_scheduled": "Site Visit Scheduled",
    "site_visit_completed": "Site Visit Completed",
    "converted": "Converted",
    "lost": "Lost",
    "qualified": "Interested",
    "site_visit": "Site Visit Scheduled",
    "negotiation": "Interested",
    "won": "Converted",
}

LEAD_STATUS_ALIASES = {
    "qualified": "interested",
    "negotiation": "interested",
    "site_visit": "site_visit_scheduled",
    "won": "converted",
}

LEAD_STATUS_TRANSITIONS = {
    "new": {"contacted"},
    "contacted": {"interested", "lost"},
    "interested": {"site_visit_scheduled", "lost"},
    "site_visit_scheduled": {"site_visit_completed", "lost"},
    "site_visit_completed": {"converted", "lost"},
    "converted": set(),
    "lost": set(),
}

LEAD_AUTOMATIC_TRANSITIONS = {
    "site_visit_scheduled": {"new", "contacted", "interested"},
    "site_visit_completed": {"new", "contacted", "interested", "site_visit_scheduled"},
    "converted": {"site_visit_completed"},
}

CONVERTED_LEAD_IMMUTABLE_FIELDS = frozenset({
    "first_name",
    "last_name",
    "phone",
    "email",
    "alt_phone",
    "address",
    "occupation",
    "budget_range",
    "preferred_location",
    "source",
    "score",
})

LEAD_SOURCE_LABELS = {
    "fb": "Facebook",
    "ig": "Instagram",
    "website": "Website",
    "site_visit": "Site Visit",
    "walk_in": "Walk-in",
    "other": "Other",
    "google": "Google",
}
