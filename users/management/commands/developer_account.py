import getpass
from pathlib import Path
from django.db import transaction

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from system_settings.audit import log_command_audit

from users.models import DeveloperAccount


class Command(BaseCommand):
    help = "Create, remove, or count server-managed Developer accounts."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("create", "remove", "list"))
        parser.add_argument("--email")
        parser.add_argument("--password-file")

    def handle(self, *args, **options):
        action = options["action"]
        email = (options.get("email") or "").strip().lower()
        if action == "list":
            self.stdout.write(f"Developers: {DeveloperAccount.objects.count()}")
            return
        if not email:
            raise CommandError("--email is required for create and remove.")
        user_model = get_user_model()
        password_file = options.get("password_file")
        file_password = None
        if action == "create" and password_file:
            path = Path(password_file)
            if not path.is_file():
                raise CommandError("Password file not found.")
            file_password = path.read_text(encoding="utf-8").strip()
            if not file_password:
                raise CommandError("Password file is empty.")
        if action == "remove":
            developer = DeveloperAccount.objects.filter(user__email__iexact=email).first()
            if developer is None:
                raise CommandError("Developer account not found.")
            with transaction.atomic():
                developer.delete()
                log_command_audit(module="developer_account", action="developer_removed", route="command:developer_account")
            self.stdout.write("Developer removed.")
            return

        user = user_model.objects.filter(email__iexact=email).first()
        if user is None:
            password = file_password if file_password is not None else getpass.getpass("Password: ")
            user = user_model.objects.create_user(username=email, email=email, password=password, is_staff=True)
        elif user.organization_memberships.filter(is_active=True).exists():
            raise CommandError("A Developer account cannot have an active organization membership.")
        with transaction.atomic():
            DeveloperAccount.objects.get_or_create(user=user)
            log_command_audit(module="developer_account", action="developer_created", route="command:developer_account")
        self.stdout.write("Developer created.")
