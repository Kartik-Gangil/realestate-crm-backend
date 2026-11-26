from decimal import Decimal
import json

from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from expenses.models import Expense, ExpenseCategory
from .models import MasterData, MasterDataCategory, SystemParameter
from .parameters import PARAMETER_REGISTRY, ParameterDefinition
from .audit import log_bulk_audit


CACHE_TTL_SECONDS = 300


def _parameter_cache_key(organization, parameter_key, project=None):
    definition = PARAMETER_REGISTRY.get(parameter_key)
    cache_project = None if definition and definition.scope == "organization" else project
    project_key = str(cache_project.pk) if cache_project is not None else "organization-default"
    return f"crm:system-parameter:{organization.pk}:{project_key}:{parameter_key}"


def _coerce_value(value, data_type):
    if data_type == SystemParameter.DataType.INTEGER:
        return int(value)
    if data_type == SystemParameter.DataType.DECIMAL:
        return Decimal(str(value))
    if data_type == SystemParameter.DataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in {"true", "1", "yes"}:
            return True
        if str(value).strip().lower() in {"false", "0", "no"}:
            return False
        raise ValueError("Invalid boolean system parameter")
    if data_type == SystemParameter.DataType.JSON and isinstance(value, str):
        return json.loads(value)
    return value


class UnknownSystemParameter(KeyError):
    pass


def parameter_definition(parameter_key):
    try:
        return PARAMETER_REGISTRY[parameter_key]
    except KeyError as error:
        raise UnknownSystemParameter(parameter_key) from error


def validate_parameter_value(parameter_key, value):
    definition = parameter_definition(parameter_key)
    try:
        if definition.data_type == SystemParameter.DataType.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("must be an integer")
            coerced = value
        elif definition.data_type == SystemParameter.DataType.DECIMAL:
            if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
                raise ValueError("must be a decimal")
            coerced = Decimal(str(value))
        elif definition.data_type == SystemParameter.DataType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError("must be a boolean")
            coerced = value
        else:
            coerced = value
    except (TypeError, ValueError, ArithmeticError) as error:
        raise ValidationError({"value": f"Invalid value for {parameter_key}: {error}."}) from error
    if definition.min_value is not None and coerced < definition.min_value:
        raise ValidationError({"value": f"Value must be at least {definition.min_value}."})
    if definition.max_value is not None and coerced > definition.max_value:
        raise ValidationError({"value": f"Value must be at most {definition.max_value}."})
    return coerced


def invalidate_system_parameter_cache(organization, parameter_key=None, project=None):
    if parameter_key is None:
        # DatabaseCache does not support wildcard deletion. Clear only the
        # known organization/project keys when a concrete key is available.
        return
    cache.delete(_parameter_cache_key(organization, parameter_key, project))


def get_system_parameter(organization, parameter_key, *, project=None):
    definition = parameter_definition(parameter_key)
    cache_key = _parameter_cache_key(organization, parameter_key, project)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    queryset = SystemParameter.objects.filter(organization=organization, parameter_key=parameter_key, is_active=True).only("value", "data_type", "project_id")
    if definition.scope == "organization":
        item = queryset.filter(project__isnull=True).first()
    elif project is not None:
        item = queryset.filter(project=project).first()
    else:
        item = queryset.filter(project__isnull=True).first()
    if not item:
        raise UnknownSystemParameter(parameter_key)
    value = _coerce_value(item.value, item.data_type)
    cache.set(cache_key, value, CACHE_TTL_SECONDS)
    return value


def clone_project_defaults(project, request=None):
    """Copy defaults without duplicating names and remap legacy expenses."""
    ensure_project_parameter_defaults(project)
    ensure_payment_mode_defaults(project.organization)
    default_masters = MasterData.objects.filter(organization=project.organization, project__isnull=True)
    existing_masters = set(MasterData.objects.filter(project=project).values_list("category_id", "code"))
    new_masters = [
        MasterData(
            organization=project.organization,
            project=project,
            category=item.category,
            code=item.code,
            name=item.name,
            color=item.color,
            description=item.description,
            properties=item.properties,
            is_active=item.is_active,
            is_system=item.is_system,
            sort_order=item.sort_order,
        )
        for item in default_masters
        if (item.category_id, item.code) not in existing_masters
    ]
    MasterData.objects.bulk_create(new_masters)
    if new_masters:
        log_bulk_audit(request=request, module="settings", action="bulk_create", instances=new_masters, organization=project.organization,
                       project=project, changed_values={"fields": ["code", "name", "category"]})
    defaults = SystemParameter.objects.filter(organization=project.organization, project__isnull=True)
    existing_parameters = set(SystemParameter.objects.filter(project=project).values_list("parameter_key", flat=True))
    new_parameters = [
        SystemParameter(
            organization=project.organization,
            project=project,
            category=item.category,
            parameter_key=item.parameter_key,
            parameter_name=item.parameter_name,
            value=item.value,
            data_type=item.data_type,
            description=item.description,
            is_active=item.is_active,
            is_critical=item.is_critical,
        )
        for item in defaults
        if item.parameter_key not in existing_parameters
    ]
    SystemParameter.objects.bulk_create(new_parameters)
    if new_parameters:
        log_bulk_audit(request=request, module="settings", action="bulk_create", instances=new_parameters, organization=project.organization,
                       project=project, changed_values={"fields": ["parameter_key", "value"]})
    category_defaults = ExpenseCategory.objects.filter(organization=project.organization, project__isnull=True)
    existing_category_rows = {
        category.name: category
        for category in ExpenseCategory.objects.filter(project=project)
    }
    category_defaults = list(category_defaults)
    missing_categories = [
        ExpenseCategory(
            organization=project.organization,
            project=project,
            name=item.name,
            description=item.description,
            is_active=item.is_active,
        )
        for item in category_defaults
        if item.name not in existing_category_rows
    ]
    ExpenseCategory.objects.bulk_create(missing_categories)
    if missing_categories:
        log_bulk_audit(request=request, module="settings", action="bulk_create", instances=missing_categories, organization=project.organization,
                       project=project, changed_values={"fields": ["name", "description"]})
    project_categories = {
        category.name: category
        for category in ExpenseCategory.objects.filter(project=project)
    }
    remapped_expenses = 0
    for default in category_defaults:
        project_category = project_categories[default.name]
        expenses = list(Expense.objects.filter(
            organization=project.organization,
            project=project,
            category__organization=project.organization,
            category__project__isnull=True,
            category__name=default.name,
        ))
        Expense.objects.filter(pk__in=[item.pk for item in expenses]).update(category=project_category)
        remapped_expenses += len(expenses)
        if expenses:
            log_bulk_audit(request=request, module="settings", action="bulk_update", instances=expenses, organization=project.organization,
                           project=project, changed_values={"category_id": project_category.pk})
    return {
        "ExpenseCategory": len(missing_categories),
        "name_matches_reused": sum(
            default.name in existing_category_rows for default in category_defaults
        ),
        "expenses_to_remap": remapped_expenses,
    }


def ensure_organization_parameter_defaults(organization):
    for definition in PARAMETER_REGISTRY.values():
        if definition.scope != "organization":
            continue
        SystemParameter.objects.get_or_create(
            organization=organization,
            project=None,
            parameter_key=definition.key,
            defaults={
                "parameter_name": definition.name,
                "value": definition.default,
                "data_type": definition.data_type,
                "description": definition.description,
            },
        )


SUPPORTED_PAYMENT_MODES = (
    ("upi", "UPI"),
    ("card", "Card"),
    ("net_banking", "Net Banking"),
    ("cash", "Cash"),
    ("cheque", "Cheque"),
)


def ensure_payment_mode_defaults(organization):
    """Provision the SSOT payment modes used by the existing manual-payment flow."""
    category, _ = MasterDataCategory.objects.get_or_create(
        code="payment_mode",
        defaults={"name": "Payment mode", "is_system": True},
    )
    for sort_order, (code, name) in enumerate(SUPPORTED_PAYMENT_MODES):
        MasterData.objects.get_or_create(
            organization=organization,
            project=None,
            category=category,
            code=code,
            defaults={"name": name, "is_system": True, "sort_order": sort_order},
        )


def ensure_lead_master_data_defaults(organization):
    from leads.constants import LEAD_SOURCE_CODES, LEAD_SOURCE_LABELS, LEAD_STATUS_CODES, LEAD_STATUS_LABELS

    categories = {
        "lead_stage": "Lead stage",
        "lead_source": "Lead source",
    }
    for code, name in categories.items():
        category, _ = MasterDataCategory.objects.get_or_create(
            code=code,
            defaults={"name": name, "is_system": True},
        )
        values = LEAD_STATUS_CODES if code == "lead_stage" else LEAD_SOURCE_CODES
        labels = LEAD_STATUS_LABELS if code == "lead_stage" else LEAD_SOURCE_LABELS
        for sort_order, item_code in enumerate(values):
            MasterData.objects.get_or_create(
                organization=organization,
                project=None,
                category=category,
                code=item_code,
                defaults={
                    "name": labels[item_code],
                    "is_system": True,
                    "sort_order": sort_order,
                },
            )


def ensure_project_parameter_defaults(project):
    ensure_organization_parameter_defaults(project.organization)
    for definition in PARAMETER_REGISTRY.values():
        if definition.scope != "project":
            continue
        SystemParameter.objects.get_or_create(
            organization=project.organization,
            project=project,
            parameter_key=definition.key,
            defaults={
                "parameter_name": definition.name,
                "value": definition.default,
                "data_type": definition.data_type,
                "description": definition.description,
            },
        )


def get_user_session_timeout_minutes(user):
    values = []
    from organizations.models import Organization

    for organization_id in user.organization_memberships.filter(is_active=True).values_list("organization_id", flat=True):
        try:
            values.append(get_system_parameter(
                organization=Organization.objects.get(pk=organization_id),
                parameter_key="auto_logout_minutes",
            ))
        except (UnknownSystemParameter, AttributeError):
            continue
    return min(values) if values else None
