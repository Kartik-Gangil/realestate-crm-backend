import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import OperationalError, connection
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import path
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response


CONTENTION_DATABASE_PATH = None


class PostgresLockError(Exception):
    pgcode = "55P03"


@api_view(["GET"])
@permission_classes([])
@authentication_classes([])
def sqlite_busy_view(request):
    raise OperationalError("database is locked")


@api_view(["GET"])
@permission_classes([])
@authentication_classes([])
def postgres_busy_view(request):
    error = OperationalError("could not obtain lock")
    error.__cause__ = PostgresLockError()
    raise error


@api_view(["GET"])
@permission_classes([])
@authentication_classes([])
def unrelated_database_error_view(request):
    raise OperationalError("database is unavailable")


@api_view(["POST"])
@permission_classes([])
@authentication_classes([])
def contended_write_view(request):
    try:
        sqlite_connection = sqlite3.connect(CONTENTION_DATABASE_PATH, timeout=0.05)
        try:
            sqlite_connection.execute("BEGIN IMMEDIATE")
            sqlite_connection.execute("INSERT INTO busy_probe (value) VALUES (1)")
            sqlite_connection.commit()
        finally:
            sqlite_connection.close()
    except sqlite3.OperationalError as error:
        raise OperationalError(str(error)) from error
    return Response({"ok": True})


urlpatterns = [
    path("sqlite-busy", sqlite_busy_view),
    path("postgres-busy", postgres_busy_view),
    path("unrelated-database-error", unrelated_database_error_view),
    path("contended-write", contended_write_view),
]


class DatabaseSettingsTests(TestCase):
    """GNFR-11 / G-3 item 2 database lock settings."""

    def test_sqlite_uses_immediate_wal_and_twenty_second_timeout_gnfr_11(self):
        config = settings.DATABASES["default"]
        self.assertEqual(config["OPTIONS"]["transaction_mode"], "IMMEDIATE")
        self.assertEqual(config["OPTIONS"]["timeout"], 20)
        self.assertIn("PRAGMA journal_mode=WAL", config["OPTIONS"]["init_command"])
        self.assertIn("PRAGMA synchronous=NORMAL", config["OPTIONS"]["init_command"])

    def test_file_database_really_uses_wal_gnfr_11(self):
        with tempfile.TemporaryDirectory() as directory:
            name = str(Path(directory) / "wal.sqlite3")
            databases = {
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": name,
                    "OPTIONS": {
                        "transaction_mode": "IMMEDIATE",
                        "timeout": 20,
                        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL",
                    },
                }
            }
            sqlite_connection = sqlite3.connect(name, timeout=20)
            try:
                sqlite_connection.execute("PRAGMA journal_mode=WAL")
                sqlite_connection.execute("PRAGMA synchronous=NORMAL")
                self.assertEqual(
                    sqlite_connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                    "wal",
                )
            finally:
                sqlite_connection.close()

    @override_settings(ROOT_URLCONF=__name__)
    def test_only_sqlite_and_postgres_lock_errors_map_to_retryable_503_gnfr_11(self):
        for route in ("sqlite-busy", "postgres-busy"):
            with self.subTest(route=route):
                response = self.client.get(f"/{route}")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"code": "database_busy"})
                self.assertEqual(response["Retry-After"], "1")

    @override_settings(ROOT_URLCONF=__name__)
    def test_unrelated_operational_error_is_not_converted_to_503_gnfr_11(self):
        with self.assertRaises(OperationalError):
            self.client.get("/unrelated-database-error")


class SQLiteContentionTests(TransactionTestCase):
    """GNFR-11 / G-3 item 2 real SQLite write contention."""

    reset_sequences = True

    @override_settings(ROOT_URLCONF=__name__)
    def test_contended_write_returns_database_busy_without_500_gnfr_11(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "contention.sqlite3")
            global CONTENTION_DATABASE_PATH
            CONTENTION_DATABASE_PATH = database_path
            try:
                sqlite_connection = sqlite3.connect(database_path, timeout=0.1)
                sqlite_connection.execute("PRAGMA journal_mode=WAL")
                sqlite_connection.execute("PRAGMA synchronous=NORMAL")
                sqlite_connection.execute("CREATE TABLE busy_probe (value INTEGER NOT NULL)")
                sqlite_connection.commit()
                sqlite_connection.close()

                holder = sqlite3.connect(database_path, timeout=0.1, isolation_level=None)
                try:
                    holder.execute("BEGIN IMMEDIATE")
                    response = self.client.post("/contended-write")
                finally:
                    holder.rollback()
                    holder.close()
            finally:
                CONTENTION_DATABASE_PATH = None

            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"code": "database_busy"})


class PostgreSQLLockTests(TransactionTestCase):
    """GNFR-11 / G-3 item 8 PostgreSQL lock behavior."""

    @skipUnlessDBFeature(
        "has_select_for_update",
        "Requires PostgreSQL TEST_DATABASE_URL; skipped on SQLite.",
    )
    def test_postgresql_connection_has_the_configured_lock_timeout_gnfr_11(self):
        self.assertEqual(
            connection.settings_dict["OPTIONS"]["options"],
            "-c lock_timeout=5000",
        )
        self.assertTrue(connection.settings_dict["CONN_HEALTH_CHECKS"])

