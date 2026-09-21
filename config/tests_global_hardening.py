from django.test import TestCase


class GlobalHardeningTests(TestCase):
    def test_metrics_endpoint_exposes_required_prometheus_series(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("crm_http_request_duration_seconds", response.content.decode())
        self.assertIn("crm_db_pool_utilization", response.content.decode())
        self.assertIn("crm_background_job_queue_depth", response.content.decode())
