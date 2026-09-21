from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from organizations.project_scope import get_current_project_id

from .models import SystemParameter


def _project_id(project):
    if project is not None:
        return getattr(project, "pk", project)
    return get_current_project_id()


def system_parameter_cache_key(organization, parameter_key, *, project=None):
    project_id = _project_id(project)
    return f"system-parameter:v1:{organization.pk}:{project_id or 'legacy'}:{parameter_key}"


def invalidate_system_parameter(organization, parameter_key, *, project=None):
    cache.delete(system_parameter_cache_key(organization, parameter_key, project=project))


def get_system_parameter(organization, parameter_key, default=None, *, project=None):
    """FR-P2-02: project-aware Redis-compatible cache-aside parameter read."""
    project_id = _project_id(project)
    cache_key = system_parameter_cache_key(
        organization,
        parameter_key,
        project=project_id,
    )
    cached = cache.get(cache_key)
    if cached is not None:
        if not cached["found"]:
            return default
        value, data_type = cached["value"], cached["data_type"]
    else:
        item = SystemParameter.objects.filter(
            organization=organization,
            project_id=project_id,
            parameter_key=parameter_key,
            is_active=True,
        ).only("value", "data_type").first()
        if item is None:
            cache.set(
                cache_key,
                {"found": False},
                timeout=settings.SYSTEM_PARAMETER_CACHE_TTL,
            )
            return default
        value, data_type = item.value, item.data_type
        cache.set(
            cache_key,
            {"found": True, "value": value, "data_type": data_type},
            timeout=settings.SYSTEM_PARAMETER_CACHE_TTL,
        )
    if data_type == SystemParameter.DataType.DECIMAL:
        return Decimal(str(value))
    return value
