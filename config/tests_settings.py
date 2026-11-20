"""Phase 0 Task 2 tests: TASK-SEC-001 and GNFR-08 (CRM_REQUIREMENTS_SPEC.md, Appendix G).

TASK-SEC-001 acceptance criteria covered here:
- `git ls-files` in both repositories lists no database file, uploaded file or `.env` file.
- With debug off and no secret key the backend refuses to start; with production variables
  `manage.py check --deploy` reports no issue other than `security.W021`.
- Previously issued tokens stop working after the revoke command runs.

The settings module is evaluated once per process, so environment scenarios run in a subprocess
with `DJANGO_ENV_FILE=none` (the local Backend/.env is never read there). Secret values are never
printed: the settings probe reports only a hash and the length of SECRET_KEY.
"""

from datetime import timedelta
import importlib
import base64
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from organizations.models import Organization, OrganizationMembership
from organizations.services import ensure_default_roles
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from users.models import UserSession
from users.security import token_hash

BACKEND_DIR = Path(settings.BASE_DIR)
FRONTEND_DIR = BACKEND_DIR.parent / "Frontend"
SUBPROCESS_TIMEOUT_SECONDS = 180
LOCAL_HOSTS = ["localhost", "127.0.0.1"]
LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
# Variables read by config/settings.py are removed from the subprocess environment so that each
# scenario sees only the variables it sets.
SETTINGS_ENV_PREFIXES = ("DJANGO_", "CORS_", "CSRF_", "FILE_ENCRYPTION_", "PRIVATE_MEDIA_")
ONE_YEAR_SECONDS = 365 * 24 * 60 * 60

SETTINGS_PROBE = """
import hashlib
import json

from django.conf import settings

names = [
    "DEBUG", "ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS",
    "CORS_ALLOW_CREDENTIALS", "CORS_ALLOW_HEADERS", "SECURE_SSL_REDIRECT",
    "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", "SECURE_HSTS_PRELOAD", "SECURE_CONTENT_TYPE_NOSNIFF",
    "SECURE_REFERRER_POLICY", "X_FRAME_OPTIONS", "SECURE_PROXY_SSL_HEADER", "LOGGING",
]
data = {name: getattr(settings, name, None) for name in names}
data["SECRET_KEY_SHA256"] = hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()
data["SECRET_KEY_LENGTH"] = len(settings.SECRET_KEY)
print("PROBE:" + json.dumps(data, default=list))
"""


def _clean_environment(**overrides):
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith(SETTINGS_ENV_PREFIXES)
    }
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DJANGO_ENV_FILE": "none",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    environment.update(overrides)
    return environment


def _run_python(args, **overrides):
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env=_clean_environment(**overrides),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )


def _file_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _production_environment(**overrides):
    environment = {
        "DJANGO_DEBUG": "0",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
        "DJANGO_ALLOWED_HOSTS": "crm.example.com",
        "CORS_ALLOWED_ORIGINS": "https://crm.example.com",
        "CSRF_TRUSTED_ORIGINS": "https://crm.example.com",
        "FILE_ENCRYPTION_KEY": _file_key(),
    }
    environment.update(overrides)
    return environment


def _tail(text, limit=3000):
    return text[-limit:]


def _env_module():
    return importlib.import_module("config.env")


class EnvHelperParsingTests(SimpleTestCase):
    """TASK-SEC-001: config/env.py parses environment values strictly and loads env files."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in list(os.environ):
            if name.startswith("CRM_TEST_") or name == "DJANGO_ENV_FILE":
                del os.environ[name]
        self.env = _env_module()
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name)

    def _write(self, name, text):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_env_str_strips_values_and_uses_default_when_unset_or_blank(self):
        self.assertEqual(self.env.env_str("CRM_TEST_VALUE", "fallback"), "fallback")
        self.assertEqual(self.env.env_str("CRM_TEST_VALUE"), "")
        os.environ["CRM_TEST_VALUE"] = "   "
        self.assertEqual(self.env.env_str("CRM_TEST_VALUE", "fallback"), "fallback")
        os.environ["CRM_TEST_VALUE"] = "  value  "
        self.assertEqual(self.env.env_str("CRM_TEST_VALUE", "fallback"), "value")

    def test_env_bool_accepts_documented_true_and_false_spellings(self):
        for raw in ("1", "true", "TRUE", "yes", "Yes", "on", " on "):
            os.environ["CRM_TEST_FLAG"] = raw
            self.assertIs(self.env.env_bool("CRM_TEST_FLAG", False), True, raw)
        for raw in ("0", "false", "False", "no", "NO", "off"):
            os.environ["CRM_TEST_FLAG"] = raw
            self.assertIs(self.env.env_bool("CRM_TEST_FLAG", True), False, raw)

    def test_env_bool_uses_default_when_unset_or_blank(self):
        self.assertIs(self.env.env_bool("CRM_TEST_FLAG", True), True)
        self.assertIs(self.env.env_bool("CRM_TEST_FLAG", False), False)
        os.environ["CRM_TEST_FLAG"] = ""
        self.assertIs(self.env.env_bool("CRM_TEST_FLAG", True), True)

    def test_env_bool_rejects_unknown_values_without_echoing_them(self):
        os.environ["CRM_TEST_FLAG"] = "maybe-sensitive-value"
        with self.assertRaises(ImproperlyConfigured) as raised:
            self.env.env_bool("CRM_TEST_FLAG", False)
        self.assertIn("CRM_TEST_FLAG", str(raised.exception))
        self.assertNotIn("maybe-sensitive-value", str(raised.exception))

    def test_env_list_splits_on_commas_and_drops_blank_items(self):
        os.environ["CRM_TEST_LIST"] = " crm.example.com, api.example.com ,, "
        self.assertEqual(self.env.env_list("CRM_TEST_LIST"), ["crm.example.com", "api.example.com"])

    def test_env_list_uses_a_copy_of_the_default_when_unset_or_blank(self):
        default = ["localhost"]
        result = self.env.env_list("CRM_TEST_LIST", default)
        self.assertEqual(result, ["localhost"])
        result.append("mutated")
        self.assertEqual(default, ["localhost"])
        os.environ["CRM_TEST_LIST"] = "  "
        self.assertEqual(self.env.env_list("CRM_TEST_LIST", default), ["localhost"])
        self.assertEqual(self.env.env_list("CRM_TEST_LIST"), [])

    def test_env_required_returns_the_value_or_raises_naming_the_variable(self):
        os.environ["CRM_TEST_REQUIRED"] = " present "
        self.assertEqual(self.env.env_required("CRM_TEST_REQUIRED"), "present")
        for missing in (None, "", "   "):
            if missing is None:
                os.environ.pop("CRM_TEST_REQUIRED", None)
            else:
                os.environ["CRM_TEST_REQUIRED"] = missing
            with self.assertRaises(ImproperlyConfigured) as raised:
                self.env.env_required("CRM_TEST_REQUIRED")
            self.assertIn("CRM_TEST_REQUIRED", str(raised.exception))

    def test_read_env_file_keeps_existing_variables_and_skips_comments(self):
        path = self._write(
            ".env",
            "# comment line\n"
            "\n"
            "CRM_TEST_PLAIN=from-file\n"
            'CRM_TEST_DOUBLE = "double quoted"\n'
            "CRM_TEST_SINGLE='single quoted'\n"
            "not a key value pair\n"
            "CRM_TEST_EXISTING=from-file\n",
        )
        os.environ["CRM_TEST_EXISTING"] = "from-process"
        self.env.read_env_file(path)
        self.assertEqual(os.environ["CRM_TEST_PLAIN"], "from-file")
        self.assertEqual(os.environ["CRM_TEST_DOUBLE"], "double quoted")
        self.assertEqual(os.environ["CRM_TEST_SINGLE"], "single quoted")
        self.assertEqual(os.environ["CRM_TEST_EXISTING"], "from-process")

    def test_load_env_file_reads_the_default_file_when_django_env_file_is_unset(self):
        default = self._write(".env", "CRM_TEST_SOURCE=default\n")
        self.assertEqual(self.env.load_env_file(default), default)
        self.assertEqual(os.environ["CRM_TEST_SOURCE"], "default")

    def test_load_env_file_tolerates_a_missing_default_file(self):
        self.assertIsNone(self.env.load_env_file(self.directory / ".env"))

    def test_django_env_file_none_loads_no_file(self):
        default = self._write(".env", "CRM_TEST_SOURCE=default\n")
        for value in ("none", "NONE", " None "):
            os.environ["DJANGO_ENV_FILE"] = value
            self.assertIsNone(self.env.load_env_file(default))
            self.assertNotIn("CRM_TEST_SOURCE", os.environ)

    def test_django_env_file_names_another_file(self):
        default = self._write(".env", "CRM_TEST_SOURCE=default\n")
        other = self._write("production.env", "CRM_TEST_SOURCE=other\n")
        os.environ["DJANGO_ENV_FILE"] = str(other)
        self.assertEqual(self.env.load_env_file(default), other)
        self.assertEqual(os.environ["CRM_TEST_SOURCE"], "other")

    def test_relative_django_env_file_resolves_against_the_default_file_directory(self):
        default = self._write(".env", "CRM_TEST_SOURCE=default\n")
        other = self._write("staging.env", "CRM_TEST_SOURCE=staging\n")
        os.environ["DJANGO_ENV_FILE"] = "staging.env"
        self.assertEqual(self.env.load_env_file(default), other)
        self.assertEqual(os.environ["CRM_TEST_SOURCE"], "staging")

    def test_missing_named_env_file_is_a_configuration_error(self):
        os.environ["DJANGO_ENV_FILE"] = str(self.directory / "missing.env")
        with self.assertRaises(ImproperlyConfigured) as raised:
            self.env.load_env_file(self.directory / ".env")
        self.assertIn("DJANGO_ENV_FILE", str(raised.exception))

    def test_blank_django_env_file_is_treated_as_unset(self):
        default = self._write(".env", "CRM_TEST_SOURCE=default\n")
        for value in ("", "   "):
            os.environ.pop("CRM_TEST_SOURCE", None)
            os.environ["DJANGO_ENV_FILE"] = value
            self.assertEqual(self.env.load_env_file(default), default)
            self.assertEqual(os.environ["CRM_TEST_SOURCE"], "default")

    def test_django_env_file_naming_a_folder_is_a_configuration_error(self):
        os.environ["DJANGO_ENV_FILE"] = str(self.directory)
        with self.assertRaises(ImproperlyConfigured) as raised:
            self.env.load_env_file(self.directory / ".env")
        self.assertIn("DJANGO_ENV_FILE", str(raised.exception))


class SettingsEnvironmentTests(SimpleTestCase):
    """TASK-SEC-001 / GNFR-08: settings come from the environment; production is locked down."""

    def _probe(self, **overrides):
        result = _run_python(["-c", SETTINGS_PROBE], **overrides)
        self.assertEqual(result.returncode, 0, msg=_tail(result.stderr))
        lines = [line for line in result.stdout.splitlines() if line.startswith("PROBE:")]
        self.assertEqual(len(lines), 1, msg=_tail(result.stdout))
        return json.loads(lines[0][len("PROBE:"):]), result

    def _assert_refuses_to_start(self, result, variable):
        self.assertNotEqual(result.returncode, 0, msg="the backend started without a valid configuration")
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(variable, result.stderr)

    def test_debug_off_without_secret_key_refuses_to_start(self):
        # DJANGO_DEBUG unset: debug defaults to off.
        self._assert_refuses_to_start(_run_python(["manage.py", "check"]), "DJANGO_SECRET_KEY")
        # Explicit DJANGO_DEBUG=0 through the WSGI entry point that production servers import.
        self._assert_refuses_to_start(
            _run_python(["-c", "import config.wsgi"], DJANGO_DEBUG="0"), "DJANGO_SECRET_KEY"
        )

    def test_debug_on_without_secret_key_uses_a_random_per_process_key_and_warns(self):
        first, first_result = self._probe(DJANGO_DEBUG="1")
        second, _ = self._probe(DJANGO_DEBUG="1")
        self.assertIs(first["DEBUG"], True)
        self.assertGreaterEqual(first["SECRET_KEY_LENGTH"], 50)
        self.assertNotEqual(first["SECRET_KEY_SHA256"], second["SECRET_KEY_SHA256"])
        self.assertIn("DJANGO_SECRET_KEY", first_result.stderr)

    def test_debug_on_without_host_or_origin_variables_uses_local_defaults(self):
        values, _ = self._probe(DJANGO_DEBUG="1")
        self.assertEqual(values["ALLOWED_HOSTS"], LOCAL_HOSTS)
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], LOCAL_ORIGINS)
        self.assertEqual(values["CSRF_TRUSTED_ORIGINS"], LOCAL_ORIGINS)

    def test_host_and_origin_variables_override_the_debug_defaults(self):
        values, _ = self._probe(
            DJANGO_DEBUG="1",
            DJANGO_SECRET_KEY=secrets.token_urlsafe(50),
            DJANGO_ALLOWED_HOSTS="crm.local, api.crm.local",
            CORS_ALLOWED_ORIGINS="https://app.crm.local",
            CSRF_TRUSTED_ORIGINS="https://app.crm.local,https://admin.crm.local",
        )
        self.assertEqual(values["ALLOWED_HOSTS"], ["crm.local", "api.crm.local"])
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], ["https://app.crm.local"])
        self.assertEqual(values["CSRF_TRUSTED_ORIGINS"], ["https://app.crm.local", "https://admin.crm.local"])

    def test_debug_off_enables_https_cookies_hsts_and_security_headers(self):
        values, _ = self._probe(**_production_environment())
        self.assertIs(values["DEBUG"], False)
        self.assertIs(values["SECURE_SSL_REDIRECT"], True)
        self.assertIs(values["SESSION_COOKIE_SECURE"], True)
        self.assertIs(values["CSRF_COOKIE_SECURE"], True)
        self.assertEqual(values["SECURE_HSTS_SECONDS"], ONE_YEAR_SECONDS)
        self.assertIs(values["SECURE_HSTS_INCLUDE_SUBDOMAINS"], True)
        self.assertIs(values["SECURE_HSTS_PRELOAD"], False)
        self.assertIs(values["SECURE_CONTENT_TYPE_NOSNIFF"], True)
        self.assertEqual(values["SECURE_REFERRER_POLICY"], "same-origin")
        self.assertEqual(values["X_FRAME_OPTIONS"], "DENY")
        self.assertIsNone(values["SECURE_PROXY_SSL_HEADER"])
        self.assertEqual(values["ALLOWED_HOSTS"], ["crm.example.com"])
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], ["https://crm.example.com"])
        self.assertEqual(values["CSRF_TRUSTED_ORIGINS"], ["https://crm.example.com"])

    def test_debug_off_has_no_local_host_or_origin_defaults(self):
        values, _ = self._probe(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=secrets.token_urlsafe(50), FILE_ENCRYPTION_KEY=_file_key())
        self.assertEqual(values["ALLOWED_HOSTS"], [])
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], [])
        self.assertEqual(values["CSRF_TRUSTED_ORIGINS"], [])

    def test_debug_off_without_file_encryption_key_refuses_to_start_gnfr_08(self):
        environment = _production_environment()
        environment.pop("FILE_ENCRYPTION_KEY")
        self._assert_refuses_to_start(_run_python(["manage.py", "check"], **environment), "FILE_ENCRYPTION_KEY")

    def test_malformed_file_encryption_key_refuses_to_start_in_both_modes_gnfr_08(self):
        bad = "not-a-valid-key-" + secrets.token_hex(8)
        for environment in (_production_environment(FILE_ENCRYPTION_KEY=bad), {"DJANGO_DEBUG": "1", "FILE_ENCRYPTION_KEY": bad}):
            with self.subTest(debug=environment["DJANGO_DEBUG"]):
                result = _run_python(["-c", SETTINGS_PROBE], **environment)
                self._assert_refuses_to_start(result, "FILE_ENCRYPTION_KEY")
                self.assertNotIn(bad, result.stdout + result.stderr)

    def test_debug_on_without_file_encryption_key_still_starts_g_4(self):
        self._probe(DJANGO_DEBUG="1")

    def test_trust_proxy_enables_the_forwarded_proto_header(self):
        values, _ = self._probe(**_production_environment(DJANGO_TRUST_PROXY="1"))
        self.assertEqual(values["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"])

    def test_django_env_file_names_the_file_to_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "production.env"
            path.write_text(
                "DJANGO_DEBUG=0\n"
                f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}\n"
                f"FILE_ENCRYPTION_KEY={_file_key()}\n"
                "DJANGO_ALLOWED_HOSTS=file.example.com\n",
                encoding="utf-8",
            )
            values, _ = self._probe(DJANGO_ENV_FILE=str(path))
        self.assertIs(values["DEBUG"], False)
        self.assertEqual(values["ALLOWED_HOSTS"], ["file.example.com"])

    def test_invalid_debug_value_refuses_to_start(self):
        self._assert_refuses_to_start(_run_python(["-c", SETTINGS_PROBE], DJANGO_DEBUG="maybe"), "DJANGO_DEBUG")

    def test_check_deploy_with_production_variables_reports_only_the_hsts_preload_notice(self):
        result = _run_python(["manage.py", "check", "--deploy"], **_production_environment())
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=_tail(output))
        issues = set(re.findall(r"\(([a-z_]+\.[A-Z]\d+)\)", output))
        self.assertEqual(issues, {"security.W021"}, msg=_tail(output))

    def test_log_level_comes_from_the_environment(self):
        values, _ = self._probe(**_production_environment(DJANGO_LOG_LEVEL="warning"))
        self.assertEqual(values["LOGGING"]["root"]["level"], "WARNING")
        self.assertEqual(values["LOGGING"]["loggers"]["django"]["level"], "WARNING")
        default_values, _ = self._probe(**_production_environment())
        self.assertEqual(default_values["LOGGING"]["root"]["level"], "INFO")
        self._assert_refuses_to_start(
            _run_python(["-c", SETTINGS_PROBE], **_production_environment(DJANGO_LOG_LEVEL="loud")),
            "DJANGO_LOG_LEVEL",
        )

    def test_sql_logging_never_drops_to_debug_because_parameters_carry_personal_data(self):
        values, _ = self._probe(**_production_environment(DJANGO_LOG_LEVEL="DEBUG"))
        self.assertEqual(values["LOGGING"]["root"]["level"], "DEBUG")
        self.assertEqual(values["LOGGING"]["loggers"]["django.db.backends"]["level"], "INFO")


class LoggingConfigurationTests(TestCase):
    """TASK-SEC-001: console logging that never records request bodies or Authorization headers."""

    TOKEN_SENTINEL = "sentinel-authorization-token-0f3c"
    PASSWORD_SENTINEL = "sentinel-request-body-password-9b1d"

    def test_logging_uses_a_console_handler_and_no_email_or_request_fields(self):
        logging_settings = settings.LOGGING
        handlers = logging_settings.get("handlers", {})
        self.assertEqual(handlers.get("console", {}).get("class"), "logging.StreamHandler")
        for name, handler in handlers.items():
            self.assertNotIn("AdminEmailHandler", handler.get("class", ""), name)
        self.assertIn("console", logging_settings.get("root", {}).get("handlers", []))
        for name, formatter in logging_settings.get("formatters", {}).items():
            for field in ("request", "body", "headers", "META", "POST", "Authorization"):
                self.assertNotIn(field, formatter.get("format", ""), name)

    def test_request_log_lines_omit_the_authorization_header_and_body(self):
        handler = logging.getHandlerByName("console")
        self.assertIsNotNone(handler, "no console handler is configured")
        request_logger = logging.getLogger("django.request")
        previous_level = request_logger.level
        request_logger.setLevel(logging.WARNING)
        stream = io.StringIO()
        previous_stream = handler.setStream(stream)
        try:
            response = APIClient().post(
                "/api/auth/login/",
                {"email": "nobody@example.com", "password": self.PASSWORD_SENTINEL},
                format="json",
                HTTP_AUTHORIZATION=f"Token {self.TOKEN_SENTINEL}",
            )
        finally:
            if previous_stream is not None:
                handler.setStream(previous_stream)
            request_logger.setLevel(previous_level)
        self.assertEqual(response.status_code, 401)
        output = stream.getvalue()
        self.assertIn("/api/auth/login/", output, "the console handler did not log the request outcome")
        self.assertNotIn(self.TOKEN_SENTINEL, output)
        self.assertNotIn(self.PASSWORD_SENTINEL, output)


class RevokeAllTokensCommandTests(TestCase):
    """TASK-SEC-001: `manage.py revoke_all_tokens --yes` revokes every previously issued API token."""

    PASSWORD = "Revoke-Test-9!"

    def setUp(self):
        user_model = get_user_model()
        self.alice = user_model.objects.create_user(
            username="revoke-alice@example.com", email="revoke-alice@example.com", password=self.PASSWORD
        )
        self.bob = user_model.objects.create_user(
            username="revoke-bob@example.com", email="revoke-bob@example.com", password=self.PASSWORD
        )
        organization = Organization.objects.create(name="Revoke Org", slug="revoke-org")
        role = ensure_default_roles(organization)["manager"]
        OrganizationMembership.objects.bulk_create([
            OrganizationMembership(organization=organization, user=self.alice, role="manager", organization_role=role),
            OrganizationMembership(organization=organization, user=self.bob, role="manager", organization_role=role),
        ])
        self.alice_key = Token.objects.create(user=self.alice).key
        self.bob_key = Token.objects.create(user=self.bob).key
        for user, key in ((self.alice, self.alice_key), (self.bob, self.bob_key)):
            UserSession.objects.create(
                user=user,
                token_hash=token_hash(key),
                expires_at=timezone.now() + timedelta(minutes=30),
            )

    def _me(self, key):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        return client.get("/api/auth/me/")

    def test_refuses_to_run_without_yes(self):
        with self.assertRaises(CommandError) as raised:
            call_command("revoke_all_tokens", stdout=io.StringIO(), stderr=io.StringIO())
        self.assertIn("--yes", str(raised.exception))
        self.assertEqual(Token.objects.count(), 2)
        self.assertEqual(self._me(self.alice_key).status_code, 200)

    def test_previously_issued_tokens_stop_working_after_revocation(self):
        self.assertEqual(self._me(self.alice_key).status_code, 200)
        self.assertEqual(self._me(self.bob_key).status_code, 200)
        output = io.StringIO()
        call_command("revoke_all_tokens", "--yes", stdout=output)
        self.assertRegex(output.getvalue(), r"\b2\b")
        self.assertNotIn(self.alice_key, output.getvalue())
        self.assertNotIn(self.bob_key, output.getvalue())
        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual(self._me(self.alice_key).status_code, 401)
        self.assertEqual(self._me(self.bob_key).status_code, 401)

    def test_reports_zero_when_there_are_no_tokens(self):
        Token.objects.all().delete()
        output = io.StringIO()
        call_command("revoke_all_tokens", "--yes", stdout=output)
        self.assertRegex(output.getvalue(), r"\b0\b")

    def test_users_can_log_in_again_and_receive_a_new_token(self):
        call_command("revoke_all_tokens", "--yes", stdout=io.StringIO())
        response = APIClient().post(
            "/api/auth/login/", {"email": "revoke-alice@example.com", "password": self.PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["token"], self.alice_key)
        self.assertEqual(self._me(response.data["token"]).status_code, 200)


def _git(repository, *args):
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )


def _is_env_file(name):
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def _forbidden_category(path):
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if ".sqlite3" in name or name.startswith(".test-db"):
        return "database"
    if parts[0] in {"media", "private_media"}:
        return "upload"
    if parts[0] == "backups":
        return "backup"
    if _is_env_file(name):
        return "env"
    return None


def _parse_env_template(path):
    entries = {}
    previous_line_is_comment = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            previous_line_is_comment = False
            continue
        if line.startswith("#"):
            previous_line_is_comment = True
            continue
        key, _, value = line.partition("=")
        entries[key.strip()] = {"value": value.strip(), "commented": previous_line_is_comment}
        previous_line_is_comment = False
    return entries


class RepositoryHygieneTests(SimpleTestCase):
    """TASK-SEC-001: no database, uploaded or .env file is tracked; templates list every key."""

    BACKEND_IGNORED = (
        "db.sqlite3",
        "db.sqlite3-wal",
        "db.sqlite3-shm",
        "media/customer_documents/sample.pdf",
        "backups/db-20260101-000000.sqlite3",
        ".test-db.sqlite3",
        ".env",
        "private_media/documents/sample.bin",
        "recovered_media/sample.pdf",
    )
    FRONTEND_IGNORED = (
        ".env",
        ".env.local",
        ".env.production",
        ".vite-cache/deps/chunk.js",
        ".pnpm-store/v10/index.json",
    )
    REQUIRED_SETTINGS_KEYS = {
        "DJANGO_SECRET_KEY",
        "DJANGO_DEBUG",
        "DJANGO_ALLOWED_HOSTS",
        "CORS_ALLOWED_ORIGINS",
        "CSRF_TRUSTED_ORIGINS",
        "DJANGO_TRUST_PROXY",
        "DJANGO_LOG_LEVEL",
    }

    def _require_repository(self, repository):
        if shutil.which("git") is None:
            self.skipTest("git is not installed, so tracked files cannot be listed")
        if not repository.is_dir():
            self.skipTest(f"{repository.name} repository is not present next to Backend")
        result = _git(repository, "rev-parse", "--is-inside-work-tree")
        if result.returncode != 0 or result.stdout.strip() != "true":
            self.skipTest(f"{repository.name} is not a git work tree")

    def _assert_tracks_no_forbidden_files(self, repository):
        self._require_repository(repository)
        result = _git(repository, "ls-files", "-z")
        self.assertEqual(result.returncode, 0, msg=_tail(result.stderr))
        counts = {}
        for path in filter(None, result.stdout.split("\0")):
            category = _forbidden_category(path)
            if category:
                counts[category] = counts.get(category, 0) + 1
        # Only counts per category are reported: upload file names can contain personal data.
        self.assertEqual(counts, {}, msg=f"{repository.name} tracks forbidden files: {counts}")

    def _assert_ignored(self, repository, ignored, not_ignored):
        self._require_repository(repository)
        for path in ignored:
            result = _git(repository, "check-ignore", "--no-index", "-q", path)
            self.assertEqual(result.returncode, 0, msg=f"{repository.name}: {path} is not ignored")
        for path in not_ignored:
            result = _git(repository, "check-ignore", "--no-index", "-q", path)
            self.assertEqual(result.returncode, 1, msg=f"{repository.name}: {path} must stay tracked")

    def _assert_template_entries(self, entries, required_keys):
        missing = sorted(set(required_keys) - set(entries))
        self.assertEqual(missing, [], msg="keys missing from .env.example")
        with_values = sorted(key for key, entry in entries.items() if entry["value"])
        self.assertEqual(with_values, [], msg=".env.example must list keys without values")
        uncommented = sorted(key for key, entry in entries.items() if not entry["commented"])
        self.assertEqual(uncommented, [], msg="every .env.example key needs a comment line above it")

    def test_backend_repository_tracks_no_database_upload_or_env_file(self):
        self._assert_tracks_no_forbidden_files(BACKEND_DIR)

    def test_frontend_repository_tracks_no_env_file(self):
        self._assert_tracks_no_forbidden_files(FRONTEND_DIR)

    def test_backend_gitignore_covers_local_data_uploads_backups_and_env(self):
        self._assert_ignored(BACKEND_DIR, self.BACKEND_IGNORED, (".env.example",))

    def test_frontend_gitignore_covers_env_files_and_local_caches(self):
        self._assert_ignored(FRONTEND_DIR, self.FRONTEND_IGNORED, (".env.example",))

    def test_backend_env_example_lists_every_settings_key_without_values(self):
        source = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
        settings_keys = set(re.findall(r"env_(?:str|bool|list|required)\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']", source))
        self.assertLessEqual(self.REQUIRED_SETTINGS_KEYS, settings_keys, msg="settings must read these keys from the environment")
        self._assert_template_entries(_parse_env_template(BACKEND_DIR / ".env.example"), settings_keys)

    def test_frontend_env_example_lists_every_vite_variable_without_values(self):
        if not FRONTEND_DIR.is_dir():
            self.skipTest("Frontend repository is not present next to Backend")
        used = set()
        for path in (FRONTEND_DIR / "src").rglob("*"):
            if path.suffix in {".ts", ".tsx"}:
                used.update(re.findall(r"import\.meta\.env\.(VITE_[A-Z0-9_]+)", path.read_text(encoding="utf-8")))
        self.assertIn("VITE_API_BASE_URL", used)
        template = FRONTEND_DIR / ".env.example"
        self.assertTrue(template.is_file(), msg="Frontend/.env.example is missing")
        self._assert_template_entries(_parse_env_template(template), used)


class CiIntegrityPolicyTests(SimpleTestCase):
    """TASK-SEC-001 / Appendix B / GNFR-10 / G-3 item 8: CI policy is explicit."""

    SCRIPTS_DIR = BACKEND_DIR.parent / "scripts"
    def test_known_failures_have_spec_and_owner_metadata(self):
        lines = [
            line.strip()
            for line in (self.SCRIPTS_DIR / "known-failures.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(lines, [])
        for line in lines:
            self.assertEqual(len(line.split("|")), 3)

    def test_ci_checks_verbose_failures_and_private_media_count(self):
        source = (self.SCRIPTS_DIR / "ci.ps1").read_text(encoding="utf-8")
        self.assertIn("'test', '--noinput', '-v', '2'", source)
        self.assertIn("@('exec', 'vitest', 'run', '--maxWorkers=2')", source)
        self.assertIn("Get-PrivateMediaFileCount", source)
        self.assertIn("Get-ObservedFailureIds", source)
        self.assertIn("known-failures mismatch", source)

    def test_ci_loads_test_database_url_key_without_echoing_it(self):
        source = (self.SCRIPTS_DIR / "ci.ps1").read_text(encoding="utf-8")
        self.assertIn("TEST_DATABASE_URL", source)
        self.assertIn("Join-Path $backendRoot '.env'", source)
        self.assertIn("Get-Content -LiteralPath $backendEnvPath", source)
        self.assertNotIn("Write-Host $candidate", source)

    def test_ci_defers_postgres_without_a_connection_attempt_g3_item_8(self):
        """G-3 item 8: owner-deferred PostgreSQL is explicit and non-connecting."""
        source = (self.SCRIPTS_DIR / "ci.ps1").read_text(encoding="utf-8")
        self.assertIn("PostgreSQL not verified (deferred by owner, G-3 item 8)", source)
        self.assertNotIn("$env:DATABASE_URL = $env:TEST_DATABASE_URL", source)
        self.assertNotIn("$backendPython manage.py test --noinput", source)
