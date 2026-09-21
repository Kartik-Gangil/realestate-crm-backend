from django.db.models.signals import post_save
from django.dispatch import receiver

from leads.models import Lead

from .services import create_customer_from_lead


@receiver(post_save, sender=Lead)
def create_customer_after_conversion(sender, instance, **kwargs):
    if instance.status == "converted":
        create_customer_from_lead(lead=instance)
