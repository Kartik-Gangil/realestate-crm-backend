from datetime import datetime
from django.db import OperationalError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.urls import path
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_success(request):
    if request.META.get("HTTP_X_TEST_VALIDATED_PROJECT") == "42":
        request._request._validated_project_id = 42
    return Response({"value": 7})


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_validation_error(request):
    raise ValidationError({"field": ["This field is invalid."]})


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_validation_detail(request):
    return Response(
        {"detail": "The project is not ready.", "field": ["Invalid project state."]},
        status=400,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def envelope_authentication_error(request):
    return Response({"unreachable": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_permission_error(request):
    raise PermissionDenied("You cannot use this endpoint.")


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_conflict_error(request):
    error = APIException("The resource conflicts with an existing record.")
    error.status_code = 409
    error.default_code = "conflict"
    raise error


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_throttled_error(request):
    raise Throttled(wait=2)


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_database_busy_error(request):
    raise OperationalError("database is locked")


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_server_error(request):
    raise RuntimeError("private exception text must not escape")


@api_view(["GET"])
@permission_classes([AllowAny])
def envelope_unlisted_client_error(request):
    return Response({"detail": "The account is not ready."}, status=418)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def envelope_project_permission_error(request):
    from organizations.services import get_organization_access, get_project_context

    access = get_organization_access(request.user, "envelope-context")
    get_project_context(request, access)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def envelope_method_not_allowed(request):
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def already_enveloped(request):
    return Response({
        "success": True,
        "data": {"expense": 1},
        "error": None,
        "meta": {"timestamp": "old", "project_id": "raw-header"},
    })


@api_view(["DELETE"])
@permission_classes([AllowAny])
def no_content(request):
    return Response(status=204)


@api_view(["GET"])
@permission_classes([AllowAny])
def private_download(request):
    response = HttpResponse(b"encrypted-file", content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="document.pdf"'
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def legacy_response(request):
    return Response({"legacy": True})


urlpatterns = [
    path("api/v1/envelope/success/", envelope_success),
    path("api/v1/envelope/validation/", envelope_validation_error),
    path("api/v1/envelope/validation-detail/", envelope_validation_detail),
    path("api/v1/envelope/authentication/", envelope_authentication_error),
    path("api/v1/envelope/permission/", envelope_permission_error),
    path("api/v1/envelope/conflict/", envelope_conflict_error),
    path("api/v1/envelope/throttled/", envelope_throttled_error),
    path("api/v1/envelope/database-busy/", envelope_database_busy_error),
    path("api/v1/envelope/server-error/", envelope_server_error),
    path("api/v1/envelope/unlisted-client-error/", envelope_unlisted_client_error),
    path("api/v1/envelope/project-permission/", envelope_project_permission_error),
    path("api/v1/envelope/method/", envelope_method_not_allowed),
    path("api/v1/envelope/already/", already_enveloped),
    path("api/v1/envelope/no-content/", no_content),
    path("api/v1/envelope/download/", private_download),
    path("api/legacy-envelope/", legacy_response),
]


@override_settings(ROOT_URLCONF=__name__)
class V1EnvelopeTests(TestCase):
    """GNFR-04 / G-2 / FR-P0-02: standard envelope is v1-only."""

    def test_success_has_exact_standard_shape_and_valid_timestamp_gnfr_04(self):
        response = self.client.get(
            "/api/v1/envelope/success/",
            HTTP_X_TEST_VALIDATED_PROJECT="42",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"success", "data", "error", "meta"})
        self.assertEqual(body["success"], True)
        self.assertEqual(body["data"], {"value": 7})
        self.assertIsNone(body["error"])
        self.assertEqual(body["meta"]["project_id"], 42)
        datetime.fromisoformat(body["meta"]["timestamp"])

    def test_organization_scope_and_unvalidated_project_have_null_project_id_gnfr_04(self):
        for headers in ({}, {"HTTP_X_PROJECT_ID": "rejected"}):
            with self.subTest(headers=headers):
                body = self.client.get("/api/v1/envelope/success/", **headers).json()
                self.assertIsNone(body["meta"]["project_id"])

    def test_error_statuses_use_standard_codes_and_preserve_details_gnfr_04(self):
        cases = (
            ("validation", 400, "validation_error"),
            ("authentication", 401, "not_authenticated"),
            ("permission", 403, "permission_denied"),
            ("missing", 404, "not_found"),
            ("method", 405, "method_not_allowed"),
            ("conflict", 409, "conflict"),
            ("throttled", 429, "throttled"),
        )
        for endpoint, status_code, error_code in cases:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(f"/api/v1/envelope/{endpoint}/")
                body = response.json()
                self.assertEqual(response.status_code, status_code)
                self.assertFalse(body["success"])
                self.assertIsNone(body["data"])
                self.assertEqual(body["error"]["code"], error_code)
                self.assertIn("message", body["error"])
                self.assertIn("details", body["error"])
                self.assertIn("meta", body)

        validation = self.client.get("/api/v1/envelope/validation/").json()
        self.assertEqual(validation["error"]["details"], {"field": ["This field is invalid."]})

    def test_view_error_message_and_field_details_are_preserved_gnfr_04(self):
        body = self.client.get("/api/v1/envelope/validation-detail/").json()

        self.assertEqual(body["error"]["message"], "The project is not ready.")
        self.assertEqual(
            body["error"]["details"],
            {"detail": "The project is not ready.", "field": ["Invalid project state."]},
        )

    def test_unlisted_client_errors_use_client_error_and_view_message_gnfr_04(self):
        body = self.client.get("/api/v1/envelope/unlisted-client-error/").json()

        self.assertEqual(body["error"]["code"], "client_error")
        self.assertEqual(body["error"]["message"], "The account is not ready.")

    def test_project_context_permission_message_is_preserved_gnfr_04_fr_p0_02(self):
        organization = make_organization("envelope-context")
        project = make_project(organization, "ENVELOPE")
        membership = make_member(organization, role="manager")
        client = APIClient()
        client.force_authenticate(membership.user)

        body = client.get(
            "/api/v1/envelope/project-permission/",
            HTTP_X_PROJECT_ID=str(project.pk),
        ).json()

        self.assertEqual(body["error"]["code"], "permission_denied")
        self.assertEqual(body["error"]["message"], "You are not assigned to this project.")

    def test_caught_exception_is_logged_without_sensitive_request_data_task_sec_001(self):
        from core.middleware.envelope import ApiV1EnvelopeMiddleware

        request = RequestFactory().get(
            "/api/v1/envelope/server-error/",
            HTTP_X_TEST_SECRET="request-header-secret",
        )

        def raise_private_error(_request):
            raise RuntimeError("private exception text must not escape")

        with self.assertLogs("core.middleware.envelope", level="ERROR") as captured:
            response = ApiV1EnvelopeMiddleware(raise_private_error)(request)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(captured.records), 1)
        line = captured.records[0].getMessage()
        self.assertIn("RuntimeError", line)
        self.assertIn("/api/v1/envelope/server-error/", line)
        self.assertNotIn("private exception text", line)
        self.assertNotIn("request-body-secret", line)
        self.assertNotIn("request-header-secret", line)

    def test_database_busy_uses_envelope_and_retry_after_gnfr_04_gnfr_11(self):
        response = self.client.get("/api/v1/envelope/database-busy/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertEqual(response.json()["error"]["code"], "database_busy")
        self.assertEqual(response.json()["error"]["details"], {"code": "database_busy"})

    def test_server_error_is_generic_and_does_not_leak_exception_text_gnfr_04(self):
        self.client.raise_request_exception = False
        response = self.client.get("/api/v1/envelope/server-error/")
        body = response.json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["error"]["code"], "server_error")
        self.assertNotIn("private exception text", str(body))
        self.assertNotIn("Traceback", str(body))

    def test_existing_envelope_gets_meta_without_double_wrapping_gnfr_04(self):
        body = self.client.get("/api/v1/envelope/already/").json()

        self.assertEqual(body["data"], {"expense": 1})
        self.assertTrue(body["success"])
        self.assertIsNone(body["error"])
        self.assertNotEqual(body["meta"]["timestamp"], "old")
        self.assertIsNone(body["meta"]["project_id"])

    def test_v1_204_becomes_an_enveloped_200_with_null_data_gnfr_04(self):
        response = self.client.delete("/api/v1/envelope/no-content/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], None)

    def test_file_download_is_not_wrapped_and_keeps_headers_g_4_gnfr_04(self):
        response = self.client.get("/api/v1/envelope/download/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"encrypted-file")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="document.pdf"')
        self.assertNotIn("success", response.content.decode())

    def test_legacy_response_keeps_its_original_body_g_2_gnfr_04(self):
        response = self.client.get("/api/legacy-envelope/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"legacy": True})

    def test_v1_response_data_remains_the_original_inner_payload_for_existing_callers_gnfr_04(self):
        success_body = self.client.get("/api/v1/envelope/success/").json()
        error_body = self.client.get("/api/v1/envelope/validation/").json()

        self.assertEqual(success_body["data"], {"value": 7})
        self.assertEqual(error_body["error"]["details"], {"field": ["This field is invalid."]})


class ProjectContextEnvelopeTests(TestCase):
    """FR-P0-02 / GNFR-04: validated project context is available to middleware."""

    def test_get_project_context_records_validated_project_on_request_fr_p0_02(self):
        from organizations.services import get_organization_access, get_project_context

        organization = make_organization("envelope-context")
        project = make_project(organization, "ENVELOPE")
        membership = make_member(organization, projects=[project])
        request = RequestFactory().get("/api/v1/organizations/envelope-context/leads/", HTTP_X_PROJECT_ID=str(project.pk))
        request.user = membership.user

        access = get_organization_access(request.user, organization.slug)
        get_project_context(request, access)

        self.assertEqual(request._validated_project_id, project.pk)
