from django.test import TestCase


class Phase0HealthEndpointTests(TestCase):
    """Coverage for FR-P0-05: liveness and readiness endpoints."""

    def test_healthz_reports_liveness(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_reports_readiness(self):
        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
