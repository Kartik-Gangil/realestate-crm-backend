from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_config_from_url


class DatabaseUrlConfigurationTests(SimpleTestCase):
    """TASK-INFRA-001: Supabase PostgreSQL database configuration."""

    def test_parses_supabase_postgresql_url_and_defaults_to_ssl(self):
        config = database_config_from_url(
            "postgresql://db%40user:pass%40word@db.example.supabase.co:5432/postgres"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "postgres")
        self.assertEqual(config["USER"], "db@user")
        self.assertEqual(config["PASSWORD"], "pass@word")
        self.assertEqual(config["HOST"], "db.example.supabase.co")
        self.assertEqual(config["PORT"], 5432)
        self.assertEqual(
            config["OPTIONS"],
            {"sslmode": "require", "options": "-c lock_timeout=5000"},
        )
        self.assertTrue(config["CONN_HEALTH_CHECKS"])

    def test_preserves_explicit_connection_options(self):
        config = database_config_from_url(
            "postgres://user:password@localhost/app?sslmode=verify-full&connect_timeout=10"
        )

        self.assertEqual(
            config["OPTIONS"],
            {
                "sslmode": "verify-full",
                "connect_timeout": "10",
                "options": "-c lock_timeout=5000",
            },
        )
        self.assertTrue(config["CONN_HEALTH_CHECKS"])

    def test_blank_url_requests_sqlite_fallback(self):
        self.assertIsNone(database_config_from_url(""))
        self.assertIsNone(database_config_from_url(None))

    def test_rejects_unsupported_or_malformed_urls(self):
        for database_url in (
            "mysql://user:password@localhost/app",
            "postgresql://user:password@/app",
            "postgresql://user:password@localhost",
        ):
            with self.subTest(database_url=database_url):
                with self.assertRaises(ImproperlyConfigured):
                    database_config_from_url(database_url)
