import os
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction



def validate_initial_password(password):
    validate_password(password)
    if (
        len(password) < 8
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
        or not re.search(r"[^A-Za-z\d]", password)
    ):
        raise ValidationError(
            "Password must be at least 8 characters and contain a letter, "
            "a number, and a symbol."
        )


class Command(BaseCommand):
    help = "Create the initial Django superuser when no superuser exists."

    def handle(self, *args, **options):
        user_model = get_user_model()

        if user_model.objects.filter(is_superuser=True).exists():
            self.stdout.write("An initial superuser already exists; no changes made.")
            return

        email = os.environ.get("DJANGO_INITIAL_SUPERUSER_EMAIL", "").strip().lower()
        password = os.environ.get("DJANGO_INITIAL_SUPERUSER_PASSWORD", "")
        first_name = os.environ.get("DJANGO_INITIAL_SUPERUSER_FIRST_NAME", "").strip()
        last_name = os.environ.get("DJANGO_INITIAL_SUPERUSER_LAST_NAME", "").strip()

        if not email or not password:
            raise CommandError(
                "DJANGO_INITIAL_SUPERUSER_EMAIL and DJANGO_INITIAL_SUPERUSER_PASSWORD "
                "are required when no superuser exists."
            )

        try:
            validate_email(email)
            validate_initial_password(password)
        except ValidationError as error:
            raise CommandError("Initial superuser credentials are invalid: %s" % "; ".join(error.messages)) from error

        try:
            with transaction.atomic():
                if user_model.objects.filter(is_superuser=True).exists():
                    self.stdout.write("An initial superuser already exists; no changes made.")
                    return
                user_model.objects.create_superuser(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
        except IntegrityError as error:
            if user_model.objects.filter(is_superuser=True).exists():
                self.stdout.write("An initial superuser already exists; no changes made.")
                return
            raise CommandError("Could not create the initial superuser.") from error

        self.stdout.write(self.style.SUCCESS("Initial superuser created."))
