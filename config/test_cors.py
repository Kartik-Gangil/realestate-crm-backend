from django.test import TestCase
from rest_framework.test import APIClient


class CorsConfigurationTests(TestCase):
    def test_vite_local_origins_receive_cors_headers(self):
        client = APIClient()
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = client.options(
                "/api/auth/login/",
                HTTP_ORIGIN=origin,
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type, x-project-id, x-idempotency-key",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Access-Control-Allow-Origin"], origin)
            self.assertIn("x-project-id", response["Access-Control-Allow-Headers"].lower())
            self.assertIn("x-idempotency-key", response["Access-Control-Allow-Headers"].lower())
