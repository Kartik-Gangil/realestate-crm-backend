from datetime import timedelta
from types import SimpleNamespace
from importlib import import_module

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from leads.models import Lead
from inventory.customer_services import create_customer
from inventory.models import Project
from core.tests.factories import make_lead
from organizations.models import Organization, OrganizationMembership
from core.tests.samples import FORGED_EXE, FORGED_HTML, SAMPLE_JPEG, SAMPLE_PNG
from .models import CustomerDocument, CustomerDocumentRequirement, DocumentCategory, EmployeeDocumentCategory
from .services import (put_document_under_verification, upload_customer_document,
                       upload_employee_document, validate_customer_documents_for_booking, verify_customer_document)


class DocumentServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reviewer", email="reviewer@example.com", password="pw")
        self.org = Organization.objects.create(name="Org", slug="org")
        self.project = Project.objects.create(organization=self.org, name="Project", code="PROJECT")
        self.lead = make_lead(self.org, self.project, first_name="Customer")
        self.customer = create_customer(organization=self.org, project=self.project, lead=self.lead, full_name="Customer", phone="9000000111")
        self.category = DocumentCategory.objects.create(organization=self.org, name="PAN", code="pan")
        CustomerDocumentRequirement.objects.create(organization=self.org, customer=self.customer, document_category=self.category)

    def upload(self):
        return upload_customer_document(organization=self.org, customer=self.customer, document_category=self.category, document_name="PAN", uploaded_file=SimpleUploadedFile("pan.pdf", b"%PDF-1.4 test", content_type="application/pdf"), user=self.user)

    def test_customer_identity_migration_uses_historical_lead_fields_lc05_rt01(self):
        migration = import_module("documents.migrations.0003_customer_identity")
        historical_lead = SimpleNamespace(first_name="Asha", last_name="Sharma")

        self.assertEqual(migration._lead_name(historical_lead), "Asha Sharma")

    def test_new_upload_archives_prior_version_and_latest_is_authoritative(self):
        first = self.upload(); first = put_document_under_verification(document=first, user=self.user); first = verify_customer_document(document=first, user=self.user)
        second = self.upload()
        first.refresh_from_db(); self.assertFalse(first.is_active); self.assertTrue(second.is_active); self.assertEqual(second.version, 2)
        validation = validate_customer_documents_for_booking(self.customer)
        self.assertFalse(validation["allowed"]); self.assertEqual(validation["pending"], ["PAN"])

    def test_verified_current_document_is_valid_and_expiry_blocks_booking(self):
        document = self.upload(); document = put_document_under_verification(document=document, user=self.user); document = verify_customer_document(document=document, user=self.user)
        self.assertTrue(validate_customer_documents_for_booking(self.customer)["allowed"])
        document.expiry_date = timezone.localdate() - timedelta(days=1); document.save()
        validation = validate_customer_documents_for_booking(self.customer)
        self.assertFalse(validation["allowed"]); self.assertEqual(validation["expired"], ["PAN"])

    def test_booking_confirmation_is_blocked_by_missing_mandatory_document(self):
        from decimal import Decimal
        from django.core.exceptions import ValidationError
        from inventory.models import Block, Plot
        from inventory.services import confirm_plot_booking, create_plot_booking
        block = Block.objects.create(organization=self.org, project=self.project, name="A", code="A")
        plot = Plot.objects.create(organization=self.org, project=self.project, block=block, plot_number="1", size=Decimal("100"))
        booking = create_plot_booking(organization=self.org, lead=self.lead, plot=plot, site_visit=None, notes="", user=self.user)
        with self.assertRaises(ValidationError) as raised:
            confirm_plot_booking(booking=booking, user=self.user)
        self.assertTrue(hasattr(raised.exception, "document_validation"))

    def test_forged_customer_document_is_rejected_task_sec_001(self):
        for name, content in (("pan.pdf", FORGED_HTML), ("pan.png", FORGED_EXE)):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError) as raised:
                    upload_customer_document(organization=self.org, customer=self.customer, document_category=self.category, document_name="PAN", user=self.user, uploaded_file=SimpleUploadedFile(name, content, content_type="application/pdf"))
                self.assertIn("file", raised.exception.message_dict)
        self.assertFalse(CustomerDocument.objects.exists())

    def test_customer_document_stores_the_detected_type_task_sec_001(self):
        document = upload_customer_document(organization=self.org, customer=self.customer, document_category=self.category, document_name="PAN", user=self.user, uploaded_file=SimpleUploadedFile("pan.png", SAMPLE_PNG, content_type="application/octet-stream"))
        self.assertEqual(document.content_type, "image/png")

    def test_employee_document_stores_the_detected_type_task_sec_001(self):
        employee = OrganizationMembership.objects.create(organization=self.org, user=self.user, role=OrganizationMembership.Role.ADMIN)
        category = EmployeeDocumentCategory.objects.create(organization=self.org, name="Offer letter", code="offer")
        document = upload_employee_document(organization=self.org, employee=employee, document_category=category, document_name="Offer", user=self.user, uploaded_file=SimpleUploadedFile("offer.jpg", SAMPLE_JPEG, content_type="application/pdf"))
        self.assertEqual(document.content_type, "image/jpeg")
