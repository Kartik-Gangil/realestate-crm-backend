from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.tests.samples import FORGED_EXE, FORGED_SVG, SAMPLE_JPEG, SAMPLE_PDF, SAMPLE_PNG
from organizations.models import Organization
from .models import OrganizationSettings
from .serializers import OrganizationSettingsSerializer


class CompanyLogoValidationTests(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Logo Org", slug="logo-org")
        self.row = OrganizationSettings.objects.create(organization=organization, company_name="Logo Org")

    def validate_logo(self, name, content):
        logo = SimpleUploadedFile(name, content, content_type="image/png")
        serializer = OrganizationSettingsSerializer(self.row, data={"company_logo": logo}, partial=True)
        return serializer.is_valid(), serializer.errors

    def test_jpeg_and_png_logos_are_accepted(self):
        for name, content in (("logo.jpg", SAMPLE_JPEG), ("logo.png", SAMPLE_PNG)):
            valid, errors = self.validate_logo(name, content)
            self.assertTrue(valid, errors)

    def test_svg_forged_and_pdf_logos_are_rejected(self):
        for name, content in (("logo.svg", FORGED_SVG), ("logo.png", FORGED_SVG), ("logo.png", FORGED_EXE), ("logo.pdf", SAMPLE_PDF)):
            valid, errors = self.validate_logo(name, content)
            self.assertFalse(valid)
            self.assertEqual(errors["company_logo"], ["Allowed file types: JPEG, PNG."])

    def test_logos_over_10_mb_are_rejected(self):
        valid, errors = self.validate_logo("logo.png", SAMPLE_PNG + b"\x00" * (10 * 1024 * 1024))
        self.assertFalse(valid)
        self.assertEqual(errors["company_logo"], ["Files must be 10 MB or smaller."])
