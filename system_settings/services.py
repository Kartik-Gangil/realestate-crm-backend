from decimal import Decimal
from .models import SystemParameter


def get_system_parameter(organization, parameter_key, default=None):
    item = SystemParameter.objects.filter(organization=organization, parameter_key=parameter_key, is_active=True).only("value", "data_type").first()
    if not item: return default
    if item.data_type == "decimal": return Decimal(str(item.value))
    return item.value
