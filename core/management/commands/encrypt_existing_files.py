"""Copy plaintext uploads into encrypted storage, printing counts only."""
from collections import Counter
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core.crypto import FileIntegrityError, current_file_key

STATUSES = ("encrypted", "to_encrypt", "already_encrypted", "missing", "conflict")


class Command(BaseCommand):
    help = "Encrypt existing plaintext uploads into private storage. Prints counts only."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--delete-originals", action="store_true")

    def handle(self, *args, **options):
        apply, delete_originals = options["apply"], options["delete_originals"]
        if delete_originals and not apply:
            raise CommandError("--delete-originals only works together with --apply.")
        source_root = Path(settings.LEGACY_MEDIA_ROOT).resolve()
        if source_root == Path(settings.MEDIA_ROOT).resolve():
            raise CommandError("LEGACY_MEDIA_ROOT and MEDIA_ROOT must be different folders.")
        current_file_key()
        per_field, totals, referenced, deleted = {}, Counter(), set(), 0
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, models.FileField):
                    continue
                label = f"{model._meta.label}.{field.name}"
                names = (model._default_manager.exclude(**{f"{field.name}__isnull": True}).exclude(**{field.name: ""})
                         .values_list(field.name, flat=True).iterator())
                for name in names:
                    referenced.add(name)
                    status, removed = self._process(source_root, name, apply, delete_originals)
                    per_field.setdefault(label, Counter())[status] += 1
                    totals[status] += 1
                    deleted += removed
        orphans = 0
        if source_root.is_dir():
            orphans = sum(1 for path in source_root.rglob("*") if path.is_file() and path.relative_to(source_root).as_posix() not in referenced)
        self.stdout.write(f"mode: {'apply' if apply else 'dry-run'}")
        for label in sorted(per_field):
            self.stdout.write(f"{label}: " + " ".join(f"{status}={per_field[label][status]}" for status in STATUSES))
        self.stdout.write("total: " + " ".join(f"{status}={totals[status]}" for status in STATUSES))
        self.stdout.write(f"orphans (files in the legacy folder that no record references): {orphans}")
        self.stdout.write(f"originals deleted: {deleted}")

    def _process(self, source_root, name, apply, delete_originals):
        source = source_root / name
        state = self._destination_state(name)
        if state == "conflict":
            return "conflict", 0
        if state == "encrypted":
            if delete_originals and source.is_file():
                source.unlink()
                return "already_encrypted", 1
            return "already_encrypted", 0
        if not source.is_file():
            return "missing", 0
        if not apply:
            return "to_encrypt", 0
        data = source.read_bytes()
        saved = default_storage.save(name, ContentFile(data))
        if saved != name:
            default_storage.delete(saved)
            return "conflict", 0
        with default_storage.open(name) as handle:
            if handle.read() != data:
                raise CommandError("An encrypted copy failed verification; its original was kept.")
        if delete_originals:
            source.unlink()
            return "encrypted", 1
        return "encrypted", 0

    @staticmethod
    def _destination_state(name):
        if not default_storage.exists(name):
            return "absent"
        try:
            with default_storage.open(name) as handle:
                handle.read()
        except FileIntegrityError:
            return "conflict"
        return "encrypted"
