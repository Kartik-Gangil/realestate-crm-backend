from datetime import date
from decimal import Decimal
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from leads.models import Lead
from documents.models import CustomerDocument
from organizations.models import Organization, OrganizationMembership
from system_settings.models import MasterData

from .models import Agreement, Block, Payment, Plot, PlotBooking, Registry, RegistryDocument
from .phase5_services import calculate_registry_charges, create_registry, transition_agreement, transition_registry


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Phase13RegistryTests(TestCase):
    """FR-P13-01..05, EC-P13-01, NFR-P13-01/02 backend coverage."""

    def setUp(self):
        from documents.models import DocumentCategory
        from leads.models import Lead
        self.user = self._user("p13-admin")
        self.organization = Organization.objects.create(name="P13 Org", slug="p13-org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role=OrganizationMembership.Role.ADMIN)
        block = Block.objects.create(organization=self.organization, name="A", code="A")
        self.plot = Plot.objects.create(organization=self.organization, block=block, plot_number="A-1", size=Decimal("100"), total_price=Decimal("1000"), status=Plot.Status.BOOKED)
        self.lead = Lead.objects.create(organization=self.organization, first_name="Registry", phone="999", ekyc_status=Lead.EkycStatus.VERIFIED)
        self.booking = PlotBooking.objects.create(organization=self.organization, lead=self.lead, plot=self.plot, status=PlotBooking.Status.CONFIRMED, final_price=Decimal("1000"), created_by=self.user)
        agreement = Agreement.objects.create(organization=self.organization, booking=self.booking, created_by=self.user)
        transition_agreement(agreement=agreement, status=Agreement.Status.READY)
        transition_agreement(agreement=agreement, status=Agreement.Status.SIGNED)
        Payment.objects.create(organization=self.organization, booking=self.booking, payment_id="P13-PAID", amount=Decimal("1000"), payment_method=Payment.Method.CASH, status=Payment.Status.SUCCESS, payment_date=date.today(), received_by=self.user)
        self.category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")

    def _user(self, username):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.create_user(username=username, password="password123")

    def _registry_with_verified_document(self, verified=True):
        registry = create_registry(booking=self.booking, created_by=self.user)
        document = CustomerDocument.objects.create(organization=self.organization, customer=self.lead, document_category=self.category, document_name="PAN", file=SimpleUploadedFile("pan.pdf", b"%PDF-1.4 valid", content_type="application/pdf"), file_name="pan.pdf", file_size=14, content_type="application/pdf", version=1, status=CustomerDocument.Status.VERIFIED if verified else CustomerDocument.Status.UPLOADED)
        RegistryDocument.objects.create(registry=registry, organization=self.organization, customer_document=document, document_label="PAN")
        registry.registry_date = date.today(); registry.save(update_fields=["registry_date", "updated_at"])
        return registry

    def test_unpaid_booking_cannot_initiate_registry(self):
        Payment.objects.filter(booking=self.booking).delete()
        with self.assertRaises(ValidationError):
            create_registry(booking=self.booking, created_by=self.user)

    def test_unverified_ekyc_blocks_registry_completion(self):
        registry = self._registry_with_verified_document()
        transition_registry(registry=registry, status=Registry.Status.IN_PROCESS, user=self.user)
        self.lead.ekyc_status = Lead.EkycStatus.PENDING; self.lead.save(update_fields=["ekyc_status", "updated_at"])
        with self.assertRaises(ValidationError):
            transition_registry(registry=registry, status=Registry.Status.COMPLETED, user=self.user)

    def test_unverified_legal_document_blocks_then_verified_document_completes(self):
        registry = self._registry_with_verified_document(verified=False)
        transition_registry(registry=registry, status=Registry.Status.IN_PROCESS, user=self.user)
        with self.assertRaises(ValidationError):
            transition_registry(registry=registry, status=Registry.Status.COMPLETED, user=self.user)
        doc = registry.documents.get().customer_document
        doc.status = CustomerDocument.Status.VERIFIED; doc.save(update_fields=["status", "updated_at"])
        transition_registry(registry=registry, status=Registry.Status.COMPLETED, user=self.user)
        self.assertEqual(registry.__class__.objects.get(pk=registry.pk).status, Registry.Status.COMPLETED)

    def test_registry_cancellation_keeps_plot_booked(self):
        registry = create_registry(booking=self.booking, created_by=self.user)
        transition_registry(registry=registry, status=Registry.Status.CANCELLED, user=self.user, remarks="Customer cancellation")
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.BOOKED)

    def test_registry_charge_calculator_supports_fixed_and_percentage(self):
        MasterData.objects.create(organization=self.organization, master_type="registry_charge_type", code="stamp", name="Stamp Duty", description="percentage:5")
        MasterData.objects.create(organization=self.organization, master_type="registry_charge_type", code="legal", name="Legal Fees", description="fixed:100")
        charges = {code: amount for code, _, _, _, amount in calculate_registry_charges(organization=self.organization, booking=self.booking, consideration_amount=Decimal("1000"))}
        self.assertEqual(charges, {"stamp": Decimal("50.00"), "legal": Decimal("100.00")})
