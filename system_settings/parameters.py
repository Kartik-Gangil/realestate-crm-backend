from dataclasses import dataclass
from decimal import Decimal

from .models import SystemParameter


@dataclass(frozen=True)
class ParameterDefinition:
    key: str
    name: str
    data_type: str
    default: object
    scope: str
    min_value: object | None = None
    max_value: object | None = None
    description: str = ""


PARAMETER_REGISTRY = {
    "auto_logout_minutes": ParameterDefinition("auto_logout_minutes", "Auto logout minutes", SystemParameter.DataType.INTEGER, 30, "organization", 5, 480),
    "site_visit_max_days_ahead": ParameterDefinition("site_visit_max_days_ahead", "Site visit maximum days ahead", SystemParameter.DataType.INTEGER, 90, "project"),
    "site_visit_reminder_days": ParameterDefinition("site_visit_reminder_days", "Site visit reminder days", SystemParameter.DataType.INTEGER, 1, "project", 0, 30),
    "plot_hold_hours": ParameterDefinition("plot_hold_hours", "Plot hold hours", SystemParameter.DataType.INTEGER, 24, "project", 1, 168),
    "booking_hold_days": ParameterDefinition("booking_hold_days", "Booking hold days", SystemParameter.DataType.INTEGER, 7, "project"),
    "payment_pending_grace_minutes": ParameterDefinition("payment_pending_grace_minutes", "Payment pending grace minutes", SystemParameter.DataType.INTEGER, 15, "project"),
    "booking_minimum_payment_percent": ParameterDefinition("booking_minimum_payment_percent", "Booking minimum payment percent", SystemParameter.DataType.INTEGER, 10, "project", 0, 100),
    "plot_selection_expiry_minutes": ParameterDefinition("plot_selection_expiry_minutes", "Plot selection expiry minutes", SystemParameter.DataType.INTEGER, 30, "project"),
    "document_expiry_warning_days": ParameterDefinition("document_expiry_warning_days", "Document expiry warning days", SystemParameter.DataType.INTEGER, 30, "project"),
    "duplicate_score_phone_exact": ParameterDefinition("duplicate_score_phone_exact", "Duplicate score phone exact", SystemParameter.DataType.INTEGER, 95, "project", 0, 100),
    "duplicate_score_phone_different_name": ParameterDefinition("duplicate_score_phone_different_name", "Duplicate score phone different name", SystemParameter.DataType.INTEGER, 90, "project", 0, 100),
    "duplicate_score_email_partial_phone": ParameterDefinition("duplicate_score_email_partial_phone", "Duplicate score email partial phone", SystemParameter.DataType.INTEGER, 80, "project", 0, 100),
    "expense_receipt_threshold": ParameterDefinition("expense_receipt_threshold", "Expense receipt threshold", SystemParameter.DataType.DECIMAL, 5000, "project"),
}


GENERAL_SETTINGS_CHOICES = {
    "date_formats": ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"],
    "currencies": ["INR", "USD", "EUR", "GBP"],
    "items_per_page": [10, 25, 50, 100],
}
