from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership
from system_settings.models import SystemParameter
from system_settings.services import invalidate_system_parameter

from .models import Block, Payment, Plot, PlotBooking, PlotStatusHistory
from .services import create_plot_booking, expire_pending_bookings


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"],
    MIGRATION_MODULES={"auth": None},
)
class Phase9BookingTests(TestCase):
    """FR-P9-03/06/08/10 and NFR-P9-01/02/03 backend coverage."""

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="phase9-manager", password="password123")
        self.organization = Organization.objects.create(name="Phase 9 Org", slug="phase9-org")
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.block = Block.objects.create(organization=self.organization, name="A", code="A")
        self.lead = Lead.objects.create(
            organization=self.organization, first_name="Ada", last_name="Lovelace", phone="111",
        )
        self.visit = Sitevisit.objects.create(organization=self.organization, lead=self.lead, site="Green")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def plot(self, number="A-101"):
        return Plot.objects.create(
            organization=self.organization, block=self.block, plot_number=number,
            size=Decimal("100.00"), total_price=Decimal("100000.00"),
        )

    def booking_payload(self, plot, **extra):
        payload = {"lead_id": self.lead.id, "plot_id": plot.id, "site_visit_id": self.visit.id}
        payload.update(extra)
        return payload

    def test_idempotency_key_reuses_booking_and_rejects_payload_change(self):
        plot = self.plot()
        url = reverse("inventory:bookings", args=[self.organization.slug])
        headers = {"HTTP_IDEMPOTENCY_KEY": "phase9-key-1"}
        first = self.client.post(url, self.booking_payload(plot), format="json", **headers)
        second = self.client.post(url, self.booking_payload(plot), format="json", **headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(PlotBooking.objects.count(), 1)
        conflict = self.client.post(url, self.booking_payload(plot, notes="different"), format="json", **headers)
        self.assertEqual(conflict.status_code, 409)

    def test_configurable_minimum_payment_and_expiry_are_enforced(self):
        SystemParameter.objects.create(
            organization=self.organization, parameter_key="booking_minimum_payment_amount",
            parameter_name="Booking minimum payment", value="2500.00",
            data_type=SystemParameter.DataType.DECIMAL,
        )
        SystemParameter.objects.create(
            organization=self.organization, parameter_key="booking_hold_window_days",
            parameter_name="Booking hold window", value=3,
            data_type=SystemParameter.DataType.INTEGER,
        )
        invalidate_system_parameter(self.organization, "booking_minimum_payment_amount")
        invalidate_system_parameter(self.organization, "booking_hold_window_days")
        plot = self.plot()
        url = reverse("inventory:bookings", args=[self.organization.slug])
        too_low = self.client.post(url, self.booking_payload(plot, initial_payment_amount="1000.00"), format="json")
        self.assertEqual(too_low.status_code, 400)
        response = self.client.post(url, self.booking_payload(plot, initial_payment_amount="2500.00"), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        booking = PlotBooking.objects.get()
        self.assertEqual(Payment.objects.filter(booking=booking).count(), 1)
        self.assertAlmostEqual((booking.hold_expires_at - booking.created_at).total_seconds(), 3 * 86400, delta=5)
        expire_pending_bookings(now=booking.hold_expires_at + timedelta(seconds=1))
        booking.refresh_from_db(); plot.refresh_from_db()
        self.assertEqual(booking.status, PlotBooking.Status.EXPIRED)
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)

    def test_confirmation_requires_qualified_verified_lead(self):
        plot = self.plot()
        create_plot_booking(
            organization=self.organization, lead=self.lead, plot=plot,
            site_visit=self.visit, notes="", user=self.user,
        )
        self.lead.is_qualified = False
        self.lead.ekyc_status = Lead.EkycStatus.PENDING
        self.lead.save(update_fields=["is_qualified", "ekyc_status", "updated_at"])
        url = reverse("inventory:booking-confirm", args=[self.organization.slug, PlotBooking.objects.get().id])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlotBooking.objects.get().status, PlotBooking.Status.PENDING)
        self.assertEqual(Plot.objects.get().status, Plot.Status.HOLD)

    def test_booking_rolls_back_when_initial_payment_creation_fails(self):
        plot = self.plot()
        with patch("inventory.services.Payment.objects.create", side_effect=ValidationError("payment unavailable")):
            with self.assertRaises(ValidationError):
                create_plot_booking(
                    organization=self.organization, lead=self.lead, plot=plot,
                    site_visit=self.visit, notes="", user=self.user,
                    initial_payment_amount=Decimal("1000.00"),
                )
        self.assertFalse(PlotBooking.objects.exists())
        self.assertEqual(Plot.objects.get().status, Plot.Status.AVAILABLE)
        self.assertFalse(PlotStatusHistory.objects.exists())

    @override_settings(ROOT_URLCONF="config.urls")
    def test_booking_receipt_is_pdf_with_sequential_number(self):
        url = reverse("inventory:bookings", args=[self.organization.slug])
        bookings = []
        for number in ("A-101", "A-102"):
            plot = self.plot(number)
            response = self.client.post(url, self.booking_payload(plot), format="json")
            self.assertEqual(response.status_code, 201)
            bookings.append(response.data["id"])
        receipt_url = reverse("inventory:booking-receipt", args=[self.organization.slug, bookings[0]])
        first = self.client.get(receipt_url)
        second = self.client.get(reverse("inventory:booking-receipt", args=[self.organization.slug, bookings[1]]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first["Content-Type"], "application/pdf")
        self.assertTrue(first.content.startswith(b"%PDF"))
        self.assertEqual(first["X-Receipt-Number"], "RCP-000001")
        self.assertEqual(second["X-Receipt-Number"], "RCP-000002")
