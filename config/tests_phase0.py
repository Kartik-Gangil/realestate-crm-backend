from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import TestCase


class Phase0HealthEndpointTests(TestCase):
    """Coverage for FR-P0-05: liveness and readiness endpoints."""

    def test_healthz_reports_liveness(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_reports_database_and_cache_readiness_fr_p0_05(self):
        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"database": "ok", "cache": "ok"})

    def test_readyz_returns_503_when_database_fails_fr_p0_05(self):
        with mock.patch.object(connection, "cursor", side_effect=RuntimeError("db down")), \
            mock.patch.object(cache, "get", return_value=None):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"database": "error", "cache": "ok"})

    def test_readyz_returns_503_when_cache_fails_fr_p0_05(self):
        with mock.patch.object(cache, "get", side_effect=RuntimeError("cache down")):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"database": "ok", "cache": "error"})
