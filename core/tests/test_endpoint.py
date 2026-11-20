from unittest.mock import patch

from django.test import TestCase, override_settings
from django.http import JsonResponse
from django.urls import path, resolve
from rest_framework.response import Response
from rest_framework.test import APIClient

from core.endpoint import crm_endpoint, public_endpoint
from core.tests.factories import make_member, make_organization, make_project


@public_endpoint
def public_marker_view(request):
    return JsonResponse({"public": True})


@crm_endpoint(["GET"], scope="user")
def user_view(request):
    return Response({"authenticated": request.user.is_authenticated})


@crm_endpoint(["GET"], scope="organization")
def organization_view(request, slug):
    return Response({"slug": request.crm_access.organization.slug, "project": request.crm_project})


@crm_endpoint(["GET"], scope="project", permissions={"GET": "leads.view"})
def project_view(request, slug):
    return Response({"project_id": request.crm_project.pk})


@crm_endpoint(["POST", "GET"], scope="organization", permissions={"POST": "leads.view"})
def audited_view(request, slug):
    return Response({"ok": True})


urlpatterns = [
    path("test/public/", public_marker_view),
    path("test/user/", user_view),
    path("test/organizations/<slug:slug>/", organization_view),
    path("test/projects/<slug:slug>/", project_view),
    path("test/audited/<slug:slug>/", audited_view),
]


@override_settings(ROOT_URLCONF=__name__)
class CrmEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.organization = make_organization("endpoint-org")
        self.project = make_project(self.organization, "ENDPOINT")
        self.member = make_member(self.organization, role="manager", projects=[self.project])

    def test_public_scope_allows_anonymous_and_marker_is_visible_gnfr_14(self):
        response = self.client.get("/test/public/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolve("/test/public/").func.public_endpoint, True)

    def test_user_scope_requires_authentication_before_view_gnfr_14(self):
        response = self.client.get("/test/user/")

        self.assertEqual(response.status_code, 401)

    def test_organization_scope_returns_404_for_unknown_and_403_for_nonmember_gnfr_14_gnfr_05(self):
        self.client.force_authenticate(self.member.user)
        self.assertEqual(self.client.get("/test/organizations/missing/").status_code, 404)

        outsider = make_member(make_organization("other-endpoint-org"), role="manager")
        self.client.force_authenticate(outsider.user)
        self.assertEqual(self.client.get("/test/organizations/endpoint-org/").status_code, 403)

    def test_project_scope_requires_valid_assigned_project_and_permission_gnfr_14_gnfr_06(self):
        self.client.force_authenticate(self.member.user)
        self.assertEqual(self.client.get("/test/projects/endpoint-org/").status_code, 400)
        self.assertEqual(
            self.client.get(
                "/test/projects/endpoint-org/",
                HTTP_X_PROJECT_ID=str(self.project.pk + 9999),
            ).status_code,
            404,
        )

        other_org = make_organization("foreign-endpoint-org")
        foreign_project = make_project(other_org, "FOREIGN")
        self.assertEqual(
            self.client.get(
                "/test/projects/endpoint-org/",
                HTTP_X_PROJECT_ID=str(foreign_project.pk),
            ).status_code,
            403,
        )

    def test_organization_scope_ignores_project_header_and_sets_request_context_gnfr_14_gnfr_06(self):
        self.client.force_authenticate(self.member.user)

        response = self.client.get(
            "/test/organizations/endpoint-org/",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["project"])

    def test_missing_permission_blocks_view_with_permission_denied_gnfr_05(self):
        self.client.force_authenticate(self.member.user)
        with patch("core.endpoint.has_permission", return_value=False):
            response = self.client.get(
                "/test/projects/endpoint-org/",
                HTTP_X_PROJECT_ID=str(self.project.pk),
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("permission", str(response.data).lower())

    def test_marker_contains_scope_and_permissions_gnfr_14(self):
        spec = resolve("/test/projects/endpoint-org/").func.crm_endpoint_spec

        self.assertEqual(spec["scope"], "project")
        self.assertEqual(spec["permissions"], {"GET": "leads.view"})

    def test_successful_mutation_records_once_but_get_and_failed_mutations_do_not_gnfr_14_gnfr_07(self):
        self.client.force_authenticate(self.member.user)
        with patch("core.endpoint.record_mutation") as record:
            self.client.get("/test/audited/endpoint-org/")
            self.client.post("/test/audited/endpoint-org/")
            self.assertEqual(record.call_count, 1)
            record.reset_mock()
            with patch("core.endpoint.has_permission", return_value=False):
                self.client.post("/test/audited/endpoint-org/")
            record.assert_not_called()
