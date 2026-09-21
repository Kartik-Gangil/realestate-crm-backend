from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Customer


@transaction.atomic
def create_customer_from_lead(*, lead):
    customer, _ = Customer.objects.get_or_create(
        organization=lead.organization,
        lead=lead,
        defaults={
            "full_name": lead.full_name,
            "phone": lead.phone,
            "email": lead.email or "",
            "status": Customer.Status.CONVERTED,
        },
    )
    if customer.status != Customer.Status.CONVERTED:
        customer.status = Customer.Status.CONVERTED
        customer.save(update_fields=["status", "updated_at"])
    return customer


def duplicate_customer(*, organization, phone="", email="", government_id="", exclude_id=None):
    query = Customer.objects.filter(organization=organization)
    if exclude_id:
        query = query.exclude(pk=exclude_id)
    conditions = []
    if phone:
        conditions.append({"phone": phone})
    if email:
        conditions.append({"email__iexact": email})
    if government_id:
        conditions.append({"government_id": government_id})
    for condition in conditions:
        match = query.filter(**condition).first()
        if match:
            return match
    return None
