from unittest.mock import call, patch

from django.test import SimpleTestCase

from users.management.commands import initialize_backend


class InitializeBackendCommandTests(SimpleTestCase):
    """TASK-MAINT-004: initialization orders migrations before bootstrap."""

    def test_runs_migrations_before_initial_superuser_bootstrap(self):
        with patch.object(initialize_backend, "call_command") as mocked_call:
            initialize_backend.Command().handle(verbosity=1)

        self.assertEqual(
            mocked_call.call_args_list,
            [
                call("migrate", interactive=False, verbosity=1),
                call("ensure_initial_superuser", verbosity=1),
            ],
        )
