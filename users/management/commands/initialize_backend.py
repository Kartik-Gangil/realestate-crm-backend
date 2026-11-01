from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run database migrations and initialize the first superuser if needed."

    def handle(self, *args, **options):
        verbosity = options.get("verbosity", 1)
        call_command("migrate", interactive=False, verbosity=verbosity)
        call_command("ensure_initial_superuser", verbosity=verbosity)
        self.stdout.write(self.style.SUCCESS("Backend initialization complete."))
