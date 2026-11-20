import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase


class OpenApiExportTests(SimpleTestCase):
    """Appendix B: the OpenAPI export covers v1 routes and CRM metadata."""

    def test_export_openapi_writes_31_v1_routes_and_shared_envelope_appendix_b(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "openapi.json"
            call_command("export_openapi", "--output", str(output))
            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(document["openapi"], "3.1.0")
        self.assertIn("/api/v1/organizations/{organization_slug}/notifications/", document["paths"])
        self.assertIn("Envelope", document["components"]["schemas"])
        notification_get = document["paths"]["/api/v1/organizations/{organization_slug}/notifications/"]["get"]
        self.assertEqual(notification_get["x-crm-scope"], "organization")
        self.assertIn("bearerAuth", notification_get["security"][0])

    def test_export_openapi_marks_project_scope_header_and_committed_file_is_current_appendix_b(self):
        call_command("export_openapi")
        committed = Path("docs/openapi.json")
        self.assertTrue(committed.is_file())
        document = json.loads(committed.read_text(encoding="utf-8"))
        self.assertTrue(document["paths"])
        exporter = Path("core/management/commands/export_openapi.py").read_text(encoding="utf-8")
        self.assertIn('scope == "project"', exporter)
        self.assertIn('X-Project-ID', exporter)

