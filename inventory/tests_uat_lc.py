"""Attached UAT report regressions for LC-08, LC-09, LC-11, LC-14 and LC-15."""

from django.test import TestCase

from organizations.models import Organization
from system_settings.models import MasterData

from .models import Project


class UatLcInventoryConfigurationTests(TestCase):
    """Project setup keeps the existing booking/payment/registry flow configured."""

    def test_new_project_has_the_five_supported_payment_modes_lc11(self):
        organization = Organization.objects.create(name="UAT LC Inventory", slug="uat-lc-inventory")
        project = Project.objects.create(organization=organization, name="UAT Project", code="LCINV")

        modes = set(
            MasterData.objects.filter(
                organization=organization,
                project=project,
                category__code="payment_mode",
                is_active=True,
            ).values_list("code", flat=True)
        )

        self.assertEqual(modes, {"upi", "card", "net_banking", "cash", "cheque"})
