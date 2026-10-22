"""NFR-P12-01 / G-4: profile photos are served only through a scoped endpoint."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_PNG
from .models import Organization, OrganizationMembership


class ProfilePhotoDownloadTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.organization = Organization.objects.create(name="Photos", slug="photos")
        other = Organization.objects.create(name="Photos other", slug="photos-other")
        self.admin = users.create_user(username="photo-admin", email="photo-admin@example.com", password="pw-123456")
        self.own_scope = users.create_user(username="photo-own", email="photo-own@example.com", password="pw-123456")
        self.outsider = users.create_user(username="photo-outsider", email="photo-outsider@example.com", password="pw-123456")
        employee_user = users.create_user(username="photo-employee", email="photo-employee@example.com", password="pw-123456")
        self.admin_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN)
        OrganizationMembership.objects.create(organization=self.organization, user=self.own_scope, role=OrganizationMembership.Role.TELECALLER,
                                              access_scope=OrganizationMembership.AccessScope.OWN)
        OrganizationMembership.objects.create(organization=other, user=self.outsider, role=OrganizationMembership.Role.ADMIN)
        self.employee = OrganizationMembership.objects.create(organization=self.organization, user=employee_user,
                                                              role=OrganizationMembership.Role.TELECALLER,
                                                              profile_photo=SimpleUploadedFile("me.png", SAMPLE_PNG))
        self.client = APIClient()

    def get(self, user, employee=None):
        self.client.force_authenticate(user)
        return self.client.get(f"/api/organizations/photos/employees/{(employee or self.employee).id}/photo/")

    def test_the_photo_downloads_as_a_protected_attachment(self):
        assert_protected_download(self, self.get(self.admin), SAMPLE_PNG, "image/png")

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(f"/api/organizations/photos/employees/{self.employee.id}/photo/").status_code, 401)

    def test_scoping_matches_the_employee_detail_endpoint(self):
        # Non-members get 403 from get_organization_access, as on every organization endpoint today.
        self.assertEqual(self.get(self.outsider).status_code, 403)
        # An "own records only" member can't see another employee.
        self.assertEqual(self.get(self.own_scope).status_code, 404)

    def test_an_employee_without_a_photo_is_404(self):
        self.assertEqual(self.get(self.admin, self.admin_membership).status_code, 404)

    def test_the_api_returns_the_endpoint_path_never_a_media_url(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(f"/api/organizations/photos/employees/{self.employee.id}/")
        self.assertEqual(response.data["profile_photo"], f"/api/organizations/photos/employees/{self.employee.id}/photo/")
        self.assertNotIn("/media/", str(response.data))
        own = self.client.get(f"/api/organizations/photos/employees/{self.admin_membership.id}/")
        self.assertIsNone(own.data["profile_photo"])
