from django.db import transaction

from inventory.models import Project

from .models import LeadCodeSequence


def next_lead_code(project):
    """Allocate a project-local lead code under the project row lock."""
    return allocate_lead_codes(project, 1)[0]


def allocate_lead_codes(project, count):
    """Allocate a contiguous block of project-local codes under one lock."""
    if count <= 0:
        return []
    with transaction.atomic():
        locked_project = Project.objects.select_for_update().get(pk=project.pk)
        sequence, _ = LeadCodeSequence.objects.get_or_create(
            project=locked_project,
            defaults={"next_number": 1},
        )
        sequence = LeadCodeSequence.objects.select_for_update().get(pk=sequence.pk)
        first_number = sequence.next_number
        sequence.next_number += count
        sequence.save(update_fields=["next_number", "updated_at"])
        return [f"{locked_project.code}-L-{number:06d}" for number in range(first_number, first_number + count)]
