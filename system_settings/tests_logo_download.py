"""NFR-P12-01 / G-4: the company logo is served only through a permission-checked endpoint."""
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_JPEG, SAMPLE_PNG
from organizations.models import Organization, OrganizationMembership
from .models import OrganizationSettings

LOGO = "/api/organizations/logos/settings/general/logo/"


class CompanyLogoDownloadTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.organization = Organization.objects.create(name="Logos", slug="logos")
        other = Organization.objects.create(name="Logos other", slug="logos-other")
        self.admin = users.create_user(username="logo-admin", email="logo-admin@example.com", password="pw-123456")
        self.telecaller = users.create_user(username="logo-caller", email="logo-caller@example.com", password="pw-123456")
        self.outsider = users.create_user(username="logo-outsider", email="logo-outsider@example.com", password="pw-123456")
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN)
        OrganizationMembership.objects.create(organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=other, user=self.outsider, role=OrganizationMembership.Role.ADMIN)
        self.row = OrganizationSettings.objects.create(organization=self.organization, company_name="Logos",
                                                       company_logo=SimpleUploadedFile("logo.png", SAMPLE_PNG))
        OrganizationSettings.objects.create(organization=other, company_name="Logos other")
        self.client = APIClient()

    def test_the_logo_downloads_as_a_protected_attachment(self):
        self.client.force_authenticate(self.admin)
        assert_protected_download(self, self.client.get(LOGO), SAMPLE_PNG, "image/png")

    def test_authentication_and_settings_view_permission_are_required(self):
        self.assertEqual(self.client.get(LOGO).status_code, 401)
        self.client.force_authenticate(self.telecaller)
        self.assertEqual(self.client.get(LOGO).status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(LOGO).status_code, 403)

    def test_no_logo_is_404(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/api/organizations/logos-other/settings/general/logo/").status_code, 404)

    def test_the_api_returns_a_versioned_endpoint_path(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/organizations/logos/settings/general/")
        self.assertTrue(response.data["company_logo"].startswith(LOGO + "?v="), response.data["company_logo"])
        self.assertNotIn("/media/", str(response.data))

    def test_a_logo_can_be_uploaded_and_removed_with_patch(self):
        self.client.force_authenticate(self.admin)
        url = "/api/organizations/logos/settings/general/"
        uploaded = self.client.patch(url, {"company_logo": SimpleUploadedFile("new.jpg", SAMPLE_JPEG)}, format="multipart")
        self.assertEqual(uploaded.status_code, 200, uploaded.data)
        self.assertTrue(uploaded.data["company_logo"].startswith(LOGO + "?v="))
        self.row.refresh_from_db()
        with default_storage.open(self.row.company_logo.name) as handle:
            self.assertEqual(handle.read(), SAMPLE_JPEG)
        removed = self.client.patch(url, {"company_logo": None}, format="json")
        self.assertEqual(removed.status_code, 200, removed.data)
        self.assertIsNone(removed.data["company_logo"])
