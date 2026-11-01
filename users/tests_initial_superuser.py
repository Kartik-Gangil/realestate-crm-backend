import io
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class InitialSuperuserCommandTests(TestCase):
    """TASK-MAINT-004: idempotent initial superuser bootstrap."""

    command_env = {
        "DJANGO_INITIAL_SUPERUSER_EMAIL": "owner@example.com",
        "DJANGO_INITIAL_SUPERUSER_PASSWORD": "Valid123!",
        "DJANGO_INITIAL_SUPERUSER_FIRST_NAME": "Owner",
        "DJANGO_INITIAL_SUPERUSER_LAST_NAME": "Account",
    }

    def test_existing_superuser_is_not_changed_and_credentials_are_not_required(self):
        user_model = get_user_model()
        existing = user_model.objects.create_superuser(
            username="existing@example.com",
            email="existing@example.com",
            password="Existing123!",
            first_name="Existing",
        )
        output = io.StringIO()

        with patch.dict(os.environ, {}, clear=False):
            for key in self.command_env:
                os.environ.pop(key, None)
            call_command("ensure_initial_superuser", stdout=output)

        existing.refresh_from_db()
        self.assertEqual(user_model.objects.filter(is_superuser=True).count(), 1)
        self.assertEqual(existing.first_name, "Existing")
        self.assertNotIn("Existing123!", output.getvalue())

    def test_missing_credentials_fail_without_creating_a_user(self):
        with patch.dict(os.environ, {key: "" for key in self.command_env}, clear=False):
            with self.assertRaises(CommandError):
                call_command("ensure_initial_superuser", stdout=io.StringIO())

        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_creates_superuser_once_and_is_idempotent(self):
        output = io.StringIO()
        with patch.dict(os.environ, self.command_env, clear=False):
            call_command("ensure_initial_superuser", stdout=output)
            call_command("ensure_initial_superuser", stdout=output)

        user_model = get_user_model()
        self.assertEqual(user_model.objects.filter(is_superuser=True).count(), 1)
        user = user_model.objects.get(is_superuser=True)
        self.assertEqual(user.username, "owner@example.com")
        self.assertEqual(user.email, "owner@example.com")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("Valid123!"))
        self.assertNotIn("Valid123!", output.getvalue())
