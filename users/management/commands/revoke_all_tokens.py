from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from users.models import UserSession


class Command(BaseCommand):
    help = "Revoke every API token."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("This deletes every API token. Re-run with --yes.")
        with transaction.atomic():
            sessions_revoked = UserSession.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
            deleted, _ = Token.objects.all().delete()
        self.stdout.write(f"Revoked {deleted} tokens and {sessions_revoked} sessions.")
