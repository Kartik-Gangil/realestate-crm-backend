from django.core.exceptions import ValidationError

from .models import Notification


def _related_fields(related):
    if related is None:
        return "", None
    if isinstance(related, tuple) and len(related) == 2:
        return str(related[0]), int(related[1])
    meta = related._meta
    return f"{meta.app_label}.{meta.model}", int(related.pk)


def notify(recipient, type, title, body, related=None, project=None):
    """Create an in-app notification without copying related IDs into text."""
    if project is not None and project.organization_id != recipient.organization_id:
        raise ValidationError({"project": "Project must belong to the recipient organization."})
    related_type, related_id = _related_fields(related)
    return Notification.objects.create(
        organization_id=recipient.organization_id,
        project=project,
        recipient_membership=recipient,
        type=str(type),
        title=str(title),
        body=str(body),
        related_object_type=related_type,
        related_object_id=related_id,
    )
