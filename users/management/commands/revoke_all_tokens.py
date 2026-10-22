from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Revoke every API token."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("This deletes every API token. Re-run with --yes.")
        deleted, _ = Token.objects.all().delete()
        self.stdout.write(f"Revoked {deleted} tokens.")
