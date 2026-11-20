from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OrganizationRole, Permission


@receiver(post_save, sender=Permission)
def grant_new_permission_to_system_admin(sender, instance, created, **kwargs):
    if not created:
        return
    for role in OrganizationRole.objects.filter(is_system=True, code="admin"):
        role.permissions.add(instance)
