import json
from pathlib import Path

from django.test import SimpleTestCase


class RailwayUatDeploymentContractTests(SimpleTestCase):
    """TASK-INFRA-002: keep the Railway UAT deployment contract explicit."""

    root = Path(__file__).resolve().parents[1]

    def test_web_config_runs_migrations_gunicorn_and_ready_healthcheck(self):
        config = json.loads((self.root / "railway.json").read_text(encoding="utf-8"))
        deploy = config["deploy"]

        self.assertEqual(deploy["preDeployCommand"], ["python manage.py migrate --noinput"])
        self.assertIn("gunicorn config.wsgi:application", deploy["startCommand"])
        self.assertIn("$PORT", deploy["startCommand"])
        self.assertEqual(deploy["healthcheckPath"], "/readyz")
        self.assertEqual(deploy["restartPolicyType"], "ALWAYS")

    def test_worker_config_runs_existing_database_task_worker(self):
        config = json.loads((self.root / "railway.worker.json").read_text(encoding="utf-8"))
        self.assertEqual(config["deploy"]["startCommand"], "python manage.py run_worker")
        self.assertEqual(config["deploy"]["restartPolicyType"], "ALWAYS")

    def test_runbook_covers_task_id_uat_database_security_and_rollback(self):
        runbook = (self.root / "docs" / "runbooks" / "railway-uat.md").read_text(encoding="utf-8")
        for required in (
            "TASK-INFRA-002",
            "DATABASE_URL",
            "Supabase",
            "DJANGO_DEBUG=false",
            "/healthz",
            "/readyz",
            "manage.py run_worker",
            "rollback",
            "demo/UAT data only",
        ):
            self.assertIn(required, runbook)

        self.assertNotRegex(runbook, r"postgres(?:ql)?://[^`\\s]+")
        self.assertNotRegex(runbook, r"(?i)(api[_-]?key|secret|password)\\s*[:=]\\s*[^<\\[\\n]+")
