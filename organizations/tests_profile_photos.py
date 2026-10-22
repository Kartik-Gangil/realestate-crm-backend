"""TASK-SEC-001 / G-4: employee profile photos must really be JPEG or PNG images, 10 MB at most."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.tests.samples import FORGED_EXE, FORGED_HTML, FORGED_SVG, SAMPLE_JPEG, SAMPLE_PDF, SAMPLE_PNG
from .employee_serializers import EmployeeCreateSerializer, EmployeeUpdateSerializer
from .models import Organization


def photo(name, content):
    return SimpleUploadedFile(name, content, content_type="image/png")


class ProfilePhotoValidationTests(TestCase):
    def test_jpeg_and_png_photos_are_accepted(self):
        for name, content in (("me.jpg", SAMPLE_JPEG), ("me.png", SAMPLE_PNG)):
            with self.subTest(name=name):
                serializer = EmployeeUpdateSerializer(data={"profile_photo": photo(name, content)})
                self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_forged_or_non_image_photos_are_rejected(self):
        for name, content in (("me.png", FORGED_EXE), ("me.png", FORGED_HTML), ("me.svg", FORGED_SVG), ("me.pdf", SAMPLE_PDF)):
            with self.subTest(name=name, content=content[:8]):
                serializer = EmployeeUpdateSerializer(data={"profile_photo": photo(name, content)})
                self.assertFalse(serializer.is_valid())
                self.assertEqual(serializer.errors["profile_photo"], ["Allowed file types: JPEG, PNG."])

    def test_photos_over_10_mb_are_rejected(self):
        serializer = EmployeeUpdateSerializer(data={"profile_photo": photo("me.png", SAMPLE_PNG + b"\x00" * (10 * 1024 * 1024))})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.errors["profile_photo"], ["Files must be 10 MB or smaller."])

    def test_the_create_serializer_checks_the_photo_too(self):
        organization = Organization.objects.create(name="Photo Org", slug="photo-org")
        data = {"email": "new.employee@example.com", "temporary_password": "password123", "first_name": "New",
                "profile_photo": photo("me.png", FORGED_EXE)}
        serializer = EmployeeCreateSerializer(data=data, context={"organization": organization})
        self.assertFalse(serializer.is_valid())
        self.assertIn("profile_photo", serializer.errors)

    def test_clearing_the_photo_is_still_allowed(self):
        serializer = EmployeeUpdateSerializer(data={"profile_photo": None})
        self.assertTrue(serializer.is_valid(), serializer.errors)
