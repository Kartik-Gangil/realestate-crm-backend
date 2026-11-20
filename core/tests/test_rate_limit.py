from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def public_probe(request):
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def protected_probe(request):
    return Response({"ok": True})


urlpatterns = [
    path("api/auth/login/", public_probe),
    path("api/auth/verify-otp/", public_probe),
    path("api/auth/forgot-password/", public_probe),
    path("api/auth/reset-password/", public_probe),
    path("api/v1/auth/login/", public_probe),
    path("api/v1/auth/verify-otp/", public_probe),
    path("api/v1/auth/forgot-password/", public_probe),
    path("api/v1/auth/reset-password/", public_probe),
    path("api/v1/rate-limited/", public_probe),
    path("healthz", public_probe),
    path("readyz", public_probe),
    path("admin/probe/", public_probe),
    path("api/protected/", protected_probe),
]


@override_settings(
    ROOT_URLCONF=__name__,
    CORS_ALLOWED_ORIGINS=["https://crm.example"],
    RATE_LIMIT_PUBLIC_PER_MINUTE=20,
    RATE_LIMIT_API_PER_MINUTE=300,
)
class RateLimitMiddlewareTests(TestCase):
    def setUp(self):
        caches["ratelimit"].clear()
        self.addCleanup(caches["ratelimit"].clear)

    def test_public_login_paths_limit_the_21st_request_and_retry_after_gnfr_14(self):
        for path in (
            "/api/auth/login/",
            "/api/auth/verify-otp/",
            "/api/auth/forgot-password/",
            "/api/auth/reset-password/",
            "/api/v1/auth/login/",
            "/api/v1/auth/verify-otp/",
            "/api/v1/auth/forgot-password/",
            "/api/v1/auth/reset-password/",
        ):
            with self.subTest(path=path):
                caches["ratelimit"].clear()
                responses = [self.client.post(path, REMOTE_ADDR="192.0.2.10") for _ in range(21)]
                self.assertEqual(responses[-1].status_code, 429)
                self.assertIn("Retry-After", responses[-1])

    def test_other_api_paths_limit_the_301st_request_gnfr_14(self):
        responses = [self.client.get("/api/v1/rate-limited/", REMOTE_ADDR="192.0.2.11") for _ in range(301)]

        self.assertEqual(responses[-2].status_code, 200)
        self.assertEqual(responses[-1].status_code, 429)

    def test_rate_limit_precedes_authentication_gnfr_14(self):
        responses = [self.client.get("/api/protected/", REMOTE_ADDR="192.0.2.12") for _ in range(301)]

        self.assertEqual(responses[0].status_code, 401)
        self.assertEqual(responses[-1].status_code, 429)

    def test_v1_throttle_is_enveloped_and_has_cors_headers_gnfr_04_gnfr_14(self):
        for _ in range(20):
            self.client.post("/api/v1/auth/login/", REMOTE_ADDR="192.0.2.13")

        response = self.client.post(
            "/api/v1/auth/login/",
            REMOTE_ADDR="192.0.2.13",
            HTTP_ORIGIN="https://crm.example",
        )
        body = response.json()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(body["error"]["code"], "throttled")
        self.assertIn("Retry-After", response)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://crm.example")

    @override_settings(DJANGO_TRUST_PROXY=False)
    def test_forwarded_for_is_ignored_without_trusted_proxy_gnfr_14(self):
        for _ in range(20):
            self.client.post(
                "/api/v1/auth/login/",
                REMOTE_ADDR="192.0.2.14",
                HTTP_X_FORWARDED_FOR="198.51.100.1",
            )

        response = self.client.post(
            "/api/v1/auth/login/",
            REMOTE_ADDR="192.0.2.14",
            HTTP_X_FORWARDED_FOR="198.51.100.2",
        )
        self.assertEqual(response.status_code, 429)

    @override_settings(DJANGO_TRUST_PROXY=True)
    def test_trusted_forwarded_for_uses_the_last_proxy_address_gnfr_14(self):
        for _ in range(20):
            self.client.post(
                "/api/v1/auth/login/",
                REMOTE_ADDR="192.0.2.15",
                HTTP_X_FORWARDED_FOR="198.51.100.1, 198.51.100.9",
            )

        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login/",
                REMOTE_ADDR="192.0.2.15",
                HTTP_X_FORWARDED_FOR="203.0.113.8, 198.51.100.9",
            ).status_code,
            429,
        )

    @override_settings(DJANGO_TRUST_PROXY=True, RATE_LIMIT_PUBLIC_PER_MINUTE=1)
    def test_trusted_proxy_rate_limit_uses_forwarded_client_not_loopback_gnfr_14(self):
        first = self.client.post(
            "/api/v1/auth/login/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.20",
        )
        same_client = self.client.post(
            "/api/v1/auth/login/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.20",
        )
        other_client = self.client.post(
            "/api/v1/auth/login/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.21",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(same_client.status_code, 429)
        self.assertEqual(other_client.status_code, 200)

    def test_health_readiness_and_admin_are_exempt_gnfr_14_fr_p0_05(self):
        for path in ("/healthz", "/readyz", "/admin/probe/"):
            with self.subTest(path=path):
                responses = [self.client.get(path, REMOTE_ADDR="192.0.2.16") for _ in range(301)]
                self.assertTrue(all(response.status_code != 429 for response in responses))

    def test_rate_limit_settings_are_documented_in_env_example_gnfr_14(self):
        env_example = __import__("pathlib").Path(__file__).resolve().parents[2] / ".env.example"
        text = env_example.read_text(encoding="utf-8")

        self.assertIn("# Public API requests per client IP per minute.", text)
        self.assertIn("RATE_LIMIT_PUBLIC_PER_MINUTE=", text)
        self.assertIn("# Non-public API requests per client IP per minute.", text)
        self.assertIn("RATE_LIMIT_API_PER_MINUTE=", text)
