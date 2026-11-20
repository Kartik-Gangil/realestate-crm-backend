from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class MetricsEndpointTests(TestCase):
    """GNFR-13: token-protected Prometheus metrics without secret leakage."""

    def setUp(self):
        self.client = APIClient()

    @override_settings(METRICS_TOKEN="metrics-secret")
    def test_metrics_requires_bearer_token_and_exposes_safe_metrics_gnfr_13(self):
        self.assertEqual(self.client.get("/metrics").status_code, 401)
        self.assertEqual(self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer wrong").status_code, 401)
        self.client.get("/healthz")
        response = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer metrics-secret")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain; version=0.0.4"))
        self.assertIn("crm_http_requests_total", response.content.decode())
        self.assertIn("crm_http_request_latency_seconds", response.content.decode())
        self.assertIn("crm_task_queue_depth", response.content.decode())
        self.assertNotIn("metrics-secret", response.content.decode())

    @override_settings(METRICS_TOKEN="")
    def test_metrics_is_not_discoverable_when_token_is_not_configured_gnfr_13(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    @override_settings(METRICS_TOKEN="métrics-secret")
    def test_non_ascii_metrics_configuration_returns_401_not_500_gnfr_13(self):
        self.client.raise_request_exception = False
        response = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer metrics-secret")
        self.assertEqual(response.status_code, 401)

