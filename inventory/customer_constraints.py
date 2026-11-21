from django.db.models import Count

from .models import Customer


def find_customer_collisions(project):
    """Return only collision counts for a project; never return identity values."""
    counts = {}
    for field in ("phone", "email", "government_id_hash"):
        counts[field] = (
            Customer.objects.filter(project=project)
            .exclude(**{field: ""})
            .values(field)
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )
    return counts
