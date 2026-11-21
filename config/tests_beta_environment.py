import os
import json
import re
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import management
from django.test import SimpleTestCase, TestCase, override_settings

from core.crypto import decode_file_key
from documents.models import DocumentCategory
from expenses.models import Expense, ExpenseCategory
from inventory.models import Payment, PaymentRefund, Plot, PlotBooking, Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission
from system_settings.models import IntegrationConfiguration, MasterData


class BetaSpecAndDeploymentTests(SimpleTestCase):
    def test_spec_records_beta_release_and_gunicorn(self):
        spec = Path(__file__).resolve().parents[2] / "CRM_REQUIREMENTS_SPEC.md"
        text = spec.read_text(encoding="utf-8")
        self.assertIn("v2.7 (2026-11-09)", text)
        self.assertIn("### G-6 Beta release (v2.7)", text)
        self.assertIn("gunicorn 26.2.0", text)
        self.assertIn("v2.9", text)
        self.assertIn("### G-7 Group sign-off (v2.9)", text)
        self.assertIn("The owner signs off once per group of phases", text)
        self.assertIn("FR-P5-02 (v2.9)", text)
        self.assertIn("FR-P12-02 (v2.9)", text)
        self.assertIn("Appendix E item 5 resolved (v2.9)", text)
        self.assertIn("minimal `customers` table", text)
        self.assertIn("Starting role templates include Accounts, Finance Head, Legal Officer, HR Admin and Site Visit Executive", text)
        self.assertIn("An approver may download an expense receipt while the expense is pending", text)
        self.assertIn("FR-P13-04 (v2.9)", text)
        self.assertIn("| v2.9 | 2026-11-17 | Final-delivery sprint owner decisions", text)

    def test_deployment_files_do_not_serve_private_media_and_define_services(self):
        root = Path(__file__).resolve().parents[2]
        nginx = (root / "deploy" / "lightsail" / "nginx-crm.conf").read_text(encoding="utf-8")
        self.assertIn("client_max_body_size 6m;", nginx)
        self.assertNotIn("private_media", nginx)
        self.assertNotIn("/private-media", nginx)
        self.assertTrue((root / "deploy" / "lightsail" / "crm-gunicorn.service").exists())
        self.assertTrue((root / "deploy" / "lightsail" / "crm-worker.service").exists())

    def test_lightsail_artifacts_use_one_application_base_path_and_static_alias(self):
        root = Path(__file__).resolve().parents[2]
        artifact_paths = (
            root / "deploy" / "lightsail" / "crm-gunicorn.service",
            root / "deploy" / "lightsail" / "crm-worker.service",
            root / "deploy" / "lightsail" / "nginx-crm.conf",
            root / "deploy" / "lightsail" / "proxy_params",
            root / "BETA_DEPLOY.md",
        )
        base_path = "/opt/shriji-crm"
        for path in artifact_paths:
            text = path.read_text(encoding="utf-8")
            for candidate in re.findall(r"/opt/[^\s`'\"]+", text):
                self.assertTrue(
                    candidate == base_path or candidate.startswith(base_path + "/"),
                    f"{path} uses a different application base path: {candidate}",
                )
        nginx = (root / "deploy" / "lightsail" / "nginx-crm.conf").read_text(encoding="utf-8")
        self.assertIn("location /static/ { alias /opt/shriji-crm/Backend/staticfiles/; }", nginx)
        self.assertIn("include /etc/nginx/proxy_params;", nginx)

    def test_proxy_params_forwards_client_and_scheme_headers(self):
        root = Path(__file__).resolve().parents[2]
        proxy_params = (root / "deploy" / "lightsail" / "proxy_params").read_text(encoding="utf-8")
        self.assertIn("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;", proxy_params)
        self.assertIn("proxy_set_header X-Forwarded-Proto $scheme;", proxy_params)
        guide = (root / "BETA_DEPLOY.md").read_text(encoding="utf-8")
        self.assertIn("cp /opt/shriji-crm/deploy/lightsail/proxy_params /etc/nginx/proxy_params", guide)

    def test_collectstatic_succeeds_with_debug_off_in_a_temporary_root(self):
        self.assertEqual(settings.STATIC_ROOT, settings.BASE_DIR / "staticfiles")
        with tempfile.TemporaryDirectory() as directory:
            static_root = Path(directory) / "staticfiles"
            with override_settings(DEBUG=False, STATIC_ROOT=static_root):
                management.call_command("collectstatic", interactive=False, verbosity=0)
            self.assertTrue(static_root.is_dir())

    def test_guide_generators_use_venv_and_produce_accepted_keys(self):
        root = Path(__file__).resolve().parents[2]
        guide = (root / "BETA_DEPLOY.md").read_text(encoding="utf-8")
        venv_marker = "sudo -u crm python3.13 -m venv .venv"
        generator_marker = "sudo -u crm .venv/bin/python -c"
        self.assertLess(guide.index(venv_marker), guide.index(generator_marker))
        self.assertIn("DJANGO_ENV_FILE=/etc/shriji-crm/crm.env", guide)
        self.assertNotIn("env $(sudo cat /etc/shriji-crm/crm.env | xargs)", guide)
        self.assertIn("sudo chown root:crm /etc/shriji-crm", guide)
        self.assertIn("sudo chmod 750 /etc/shriji-crm", guide)
        self.assertIn("sudo -u crm git", guide)
        self.assertIn("VITE_API_BASE_URL=", guide)

        integration_code = re.search(
            r"sudo -u crm \.venv/bin/python -c \"([^\"]+)\"\s+# INTEGRATION_ENCRYPTION_KEY",
            guide,
        ).group(1)
        file_code = re.search(
            r"sudo -u crm \.venv/bin/python -c \"([^\"]+)\"\s+# FILE_ENCRYPTION_KEY",
            guide,
        ).group(1)
        for code in (integration_code, file_code):
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
            generated = result.stdout.strip()
            self.assertTrue(generated)
            if "Fernet.generate_key" in code:
                Fernet(generated.encode("ascii"))
            else:
                decode_file_key(generated)

    def test_beta_main_flow_is_in_normal_core_test_discovery(self):
        root = Path(__file__).resolve().parents[2]
        self.assertTrue((root / "Backend" / "core" / "tests" / "test_beta_main_flow.py").exists())
        self.assertFalse((root / ".agents" / "tasks" / "beta" / "test_beta_main_flow.py").exists())
        self.assertFalse((root / ".agents" / "tasks" / "__init__.py").exists())
        self.assertFalse((root / ".agents" / "tasks" / "beta" / "__init__.py").exists())
        ci = (root / "scripts" / "ci.ps1").read_text(encoding="utf-8")
        self.assertNotIn("--pythonpath", ci)
        self.assertIn("core.tests.test_beta_main_flow", ci)

    def test_release_notes_record_the_accepted_generic_error_gap(self):
        root = Path(__file__).resolve().parents[2]
        release_notes = (root / "BETA_RELEASE_NOTES.md").read_text(encoding="utf-8")
        self.assertIn("steps 16 and 26", release_notes)
        self.assertIn("generic error", release_notes)

    def test_beta_artifacts_use_the_task_layout_and_owner_wording(self):
        root = Path(__file__).resolve().parents[2]
        beta = root / ".agents" / "tasks" / "beta"
        for name in (
            "inventory.md",
            "BETA_E2E_SCRIPT.md",
            "BETA_REPORT.md",
        ):
            self.assertTrue((beta / name).exists(), name)
        self.assertTrue((root / "Backend" / "core" / "tests" / "test_beta_main_flow.py").exists())
        self.assertFalse((root / "STATUS.md").exists())
        self.assertFalse((beta / "STATUS.md").exists())
        status = (root / ".agents" / "tasks" / "phase-0" / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("test_beta_main_flow.py", status)
        self.assertIn("BETA_E2E_SCRIPT.md", status)
        self.assertIn("Phase 4: **signed off", status)

    def test_beta_deploy_is_owner_runnable_and_has_required_checks(self):
        root = Path(__file__).resolve().parents[2]
        guide = (root / "BETA_DEPLOY.md").read_text(encoding="utf-8")
        required_phrases = (
            "Ubuntu 24.04",
            "Lightsail console",
            "DATABASE_URL=",
            "DJANGO_HTTPS=false",
            "DJANGO_HTTPS=true",
            "seed_beta_demo",
            "systemd-analyze verify",
            "nginx -t",
            "certbot",
            "journalctl",
            "502 from nginx",
            "CORS errors",
            "Worker not running",
            "Imports stuck at 0%",
            "sudo -u crm mkdir -p private_media",
            "sudo chmod 755 /opt/shriji-crm /opt/shriji-crm/Frontend /opt/shriji-crm/Backend",
            "sudo chmod -R o+rX /opt/shriji-crm/Frontend/dist /opt/shriji-crm/Backend/staticfiles",
            "sudo chmod 700 /opt/shriji-crm/Backend/private_media",
            "sudo chmod 600 /opt/shriji-crm/Backend/db.sqlite3",
            "sudo -u www-data test -r /opt/shriji-crm/Frontend/dist/index.html",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, guide)
        self.assertLess(guide.index("pnpm build"), guide.index("mkdir -p private_media"))

    def test_ci_explicitly_runs_relocated_beta_main_flow_test(self):
        root = Path(__file__).resolve().parents[2]
        ci = (root / "scripts" / "ci.ps1").read_text(encoding="utf-8")
        self.assertIn("test_beta_main_flow.py", ci)
        self.assertIn("core.tests.test_beta_main_flow", ci)


class HttpsSwitchTests(SimpleTestCase):
    def _probe(self, **values):
        env = os.environ.copy()
        env.update(values)
        env["DJANGO_SECRET_KEY"] = "beta-test-secret"
        env["FILE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        result = subprocess.run(
            [sys.executable, "-c", """
import json
from django.conf import settings
print(json.dumps({
    'redirect': getattr(settings, 'SECURE_SSL_REDIRECT', False),
    'session': getattr(settings, 'SESSION_COOKIE_SECURE', False),
    'csrf': getattr(settings, 'CSRF_COOKIE_SECURE', False),
    'hsts': getattr(settings, 'SECURE_HSTS_SECONDS', 0),
    'nosniff': settings.SECURE_CONTENT_TYPE_NOSNIFF,
    'referrer': settings.SECURE_REFERRER_POLICY,
    'frame': settings.X_FRAME_OPTIONS,
}))
"""],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_production_https_defaults_on(self):
        values = self._probe(DJANGO_DEBUG="0")
        self.assertTrue(values["redirect"])
        self.assertTrue(values["session"])
        self.assertTrue(values["csrf"])
        self.assertEqual(values["hsts"], 31536000)

    def test_http_only_switch_disables_only_https_enforcement(self):
        values = self._probe(DJANGO_DEBUG="0", DJANGO_HTTPS="0")
        self.assertFalse(values["redirect"])
        self.assertFalse(values["session"])
        self.assertFalse(values["csrf"])
        self.assertEqual(values["hsts"], 0)
        self.assertTrue(values["nosniff"])
        self.assertEqual(values["referrer"], "same-origin")
        self.assertEqual(values["frame"], "DENY")


class BetaSeedCommandTests(TestCase):
    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_refuses_non_demo_slug_without_writing(self):
        with self.assertRaises(management.CommandError):
            management.call_command("seed_beta_demo", organization="not-demo", project="DEMO")
        self.assertFalse(Organization.objects.filter(slug="not-demo").exists())

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_is_idempotent_isolated_and_does_not_print_passwords(self):
        other = Organization.objects.create(name="Other", slug="other-org")
        other_project = Project.objects.create(organization=other, name="Other", code="OTHER")
        before = (Organization.objects.count(), Project.objects.count(), Lead.objects.count())
        first_output = StringIO()
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
            management.call_command("seed_beta_demo", organization="demo-beta", project="DEMO", stdout=first_output)
            password_values = [line.split("=", 1)[1] for line in password_file.read_text(encoding="utf-8").splitlines() if "=" in line]
            second_output = StringIO()
            management.call_command("seed_beta_demo", organization="demo-beta", project="DEMO", stdout=second_output)
        password_file.unlink(missing_ok=True)
        counts = {
            "org": Organization.objects.filter(slug="demo-beta").count(),
            "project": Project.objects.filter(code="DEMO").count(),
            "roles": OrganizationRole.objects.filter(organization__slug="demo-beta").count(),
            "users": OrganizationMembership.objects.filter(organization__slug="demo-beta").count(),
            "leads": Lead.objects.filter(organization__slug="demo-beta").count(),
            "plots": Plot.objects.filter(organization__slug="demo-beta").count(),
            "integrations": IntegrationConfiguration.objects.filter(organization__slug="demo-beta").count(),
        }
        self.assertEqual(counts["org"], 1)
        self.assertEqual(counts["project"], 1)
        self.assertGreaterEqual(counts["users"], 4)
        self.assertEqual(counts["leads"], 5)
        self.assertGreaterEqual(counts["plots"], 20)
        self.assertGreaterEqual(counts["integrations"], 2)
        self.assertEqual(counts["org"], Organization.objects.filter(slug="demo-beta").count())
        self.assertEqual(counts["leads"], Lead.objects.filter(organization__slug="demo-beta").count())
        self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
        self.assertEqual(before[0] + 1, Organization.objects.count())
        self.assertTrue(password_values)
        self.assertTrue(all(value not in first_output.getvalue() for value in password_values))
        self.assertTrue(all(value not in second_output.getvalue() for value in password_values))

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_includes_accounts_credentials_for_phase16_reimbursement_flow(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
            management.call_command("seed_beta_demo", organization="demo-beta-accounts", project="DEMO", stdout=StringIO())
        credentials = password_file.read_text(encoding="utf-8")
        password_file.unlink(missing_ok=True)

        membership = OrganizationMembership.objects.get(
            organization__slug="demo-beta-accounts",
            user__username="accounts@demo-beta-accounts.invalid",
        )
        self.assertEqual(membership.organization_role.code, "accounts")
        self.assertIn("accounts=", credentials)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_links_demo_employee_to_manager_for_phase15_and_grants_employee_expense_flow(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        try:
            with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                management.call_command("seed_beta_demo", organization="demo-beta-phase15-16", project="DEMO", stdout=StringIO())

            employee = OrganizationMembership.objects.get(
                organization__slug="demo-beta-phase15-16",
                user__username="telecaller@demo-beta-phase15-16.invalid",
            )
            manager = OrganizationMembership.objects.get(
                organization__slug="demo-beta-phase15-16",
                user__username="manager@demo-beta-phase15-16.invalid",
            )
            self.assertEqual(employee.reporting_manager_id, manager.id)
            self.assertTrue(employee.organization_role.permissions.filter(module="expenses", action="view_own").exists())
            self.assertTrue(employee.organization_role.permissions.filter(module="expenses", action="view").exists())
            self.assertTrue(employee.organization_role.permissions.filter(module="expenses", action="edit_own").exists())
            self.assertTrue(employee.organization_role.permissions.filter(module="expenses", action="submit").exists())
        finally:
            password_file.unlink(missing_ok=True)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_creates_customer_document_categories_for_beta_flow(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        try:
            with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                management.call_command("seed_beta_demo", organization="demo-beta-documents", project="DEMO", stdout=StringIO())

            organization = Organization.objects.get(slug="demo-beta-documents")
            self.assertTrue(
                DocumentCategory.objects.filter(
                    organization=organization,
                    code="id-proof",
                    name="ID Proof",
                    is_active=True,
                ).exists()
            )
        finally:
            password_file.unlink(missing_ok=True)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_creates_project_payment_modes_for_beta_flow(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        try:
            with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                management.call_command("seed_beta_demo", organization="demo-beta-payment-modes", project="DEMO", stdout=StringIO())

            organization = Organization.objects.get(slug="demo-beta-payment-modes")
            project = Project.objects.get(organization=organization, code="DEMO")
            self.assertTrue(
                MasterData.objects.filter(
                    organization=organization,
                    project=project,
                    category__code="payment_mode",
                    code="cash",
                    name="Cash",
                    is_active=True,
                ).exists()
            )
        finally:
            password_file.unlink(missing_ok=True)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_extended_fixtures_seed_only_demo_org_data_for_browser_acceptance(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                    management.call_command(
                        "seed_beta_demo",
                        organization="demo-beta-3",
                        project="DEMO3",
                        with_extended_fixtures=True,
                        stdout=StringIO(),
                    )
        password_file.unlink(missing_ok=True)

        organization = Organization.objects.get(slug="demo-beta-3")
        project = Project.objects.get(organization=organization, code="DEMO3")
        booked_lead = Lead.objects.get(organization=organization, email="booked.demo.invalid")
        booking = PlotBooking.objects.get(organization=organization, lead=booked_lead, status=PlotBooking.Status.CONFIRMED)
        payment = Payment.objects.get(organization=organization, booking=booking, status=Payment.Status.SUCCESS)
        self.assertFalse(PaymentRefund.objects.filter(organization=organization, payment=payment).exists())

        telecaller = get_user_model().objects.get(username="telecaller@demo-beta-3.invalid")
        category = ExpenseCategory.objects.get(organization=organization, project=project, name="Browser acceptance expense")
        expense = Expense.objects.get(expense_id="BETA-EXTENDED-EXPENSE")
        self.assertEqual(expense.organization_id, organization.id)
        self.assertEqual(expense.project_id, project.id)
        self.assertEqual(expense.submitted_by_id, telecaller.id)
        self.assertEqual(expense.category_id, category.id)
        self.assertEqual(expense.status, Expense.Status.PENDING_APPROVAL)
        self.assertTrue(expense.receipt.name)
        self.assertIn("expenses/demo-beta-3/", expense.receipt.name)
        self.assertEqual(Organization.objects.exclude(slug__startswith="demo-").filter(expenses__isnull=False).count(), 0)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_extended_seed_does_not_reuse_an_approved_fixture_from_another_demo_org(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                    management.call_command(
                        "seed_beta_demo",
                        organization="demo-beta-collision-a",
                        project="DEMOA",
                        with_extended_fixtures=True,
                        stdout=StringIO(),
                    )
                    first_expense = Expense.objects.get(expense_id="BETA-EXTENDED-EXPENSE")
                    first_expense.status = Expense.Status.APPROVED
                    first_expense.save(update_fields=["status"])

                    management.call_command(
                        "seed_beta_demo",
                        organization="demo-beta-collision-b",
                        project="DEMOB",
                        with_extended_fixtures=True,
                        stdout=StringIO(),
                    )

        password_file.unlink(missing_ok=True)
        self.assertEqual(Expense.objects.get(expense_id="BETA-EXTENDED-EXPENSE").organization.slug, "demo-beta-collision-a")
        second_expense = Expense.objects.exclude(expense_id="BETA-EXTENDED-EXPENSE").get(organization__slug="demo-beta-collision-b")
        self.assertTrue(second_expense.expense_id.startswith("BETA-EXTENDED-EXPENSE-"))
        self.assertEqual(second_expense.status, Expense.Status.PENDING_APPROVAL)

    def test_custom_site_visit_role_has_only_step_permissions(self):
        role = OrganizationRole.objects.create(name="Site Visit Executive", code="site-visit-executive", organization=Organization.objects.create(name="Role Org", slug="demo-role"))
        Permission.objects.get_or_create(module="site_visits", action="view", defaults={"name": "View site visits", "scope": "project"})
        role.permissions.set(Permission.objects.filter(module="site_visits", action__in=["view", "edit", "add"]))
        self.assertTrue(role.permissions.exists())
        self.assertFalse(role.permissions.filter(module="settings").exists())

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seed_refreshes_credentials_when_file_belongs_to_another_demo_org(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
            management.call_command("seed_beta_demo", organization="demo-beta-a", project="DEMO", stdout=StringIO())
            management.call_command("seed_beta_demo", organization="demo-beta-b", project="DEMO", stdout=StringIO())
            management.call_command("seed_beta_demo", organization="demo-beta-a", project="DEMO", stdout=StringIO())
        try:
            passwords = {
                line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in password_file.read_text(encoding="utf-8").splitlines()
                if "=" in line
            }
            User = get_user_model()
            for role in ("admin", "manager", "telecaller", "site-visit-executive"):
                user = User.objects.get(username=f"{role}@demo-beta-a.invalid")
                self.assertTrue(user.check_password(passwords[role]))
        finally:
            password_file.unlink(missing_ok=True)

    @override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_seeded_manager_can_schedule_site_visits(self):
        password_root = Path(__file__).resolve().parents[1]
        password_file = password_root / "crm-beta-demo-passwords.txt"
        password_file.unlink(missing_ok=True)
        try:
            with patch("inventory.management.commands.seed_beta_demo.Path.home", return_value=password_root):
                management.call_command("seed_beta_demo", organization="demo-beta-site-visits", project="DEMO", stdout=StringIO())

            role = OrganizationRole.objects.get(organization__slug="demo-beta-site-visits", code="manager")
            self.assertTrue(role.permissions.filter(module="site_visits", action="view").exists())
            self.assertTrue(role.permissions.filter(module="site_visits", action="add").exists())
            self.assertTrue(role.permissions.filter(module="site_visits", action="edit").exists())
            self.assertTrue(role.permissions.filter(module="telecalling", action="view").exists())

            executive_role = OrganizationRole.objects.get(
                organization__slug="demo-beta-site-visits", code="site-visit-executive"
            )
            self.assertTrue(executive_role.permissions.filter(module="plots", action="view").exists())
        finally:
            password_file.unlink(missing_ok=True)
