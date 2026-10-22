"""TASK-SEC-001 / G-4: existing plaintext uploads are encrypted by a command with a dry run."""
import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.crypto import MAGIC
from core.tests.samples import SAMPLE_PDF, SAMPLE_PNG
from organizations.models import Organization
from system_settings.models import OrganizationSettings

FIELD = "system_settings.OrganizationSettings.company_logo"
SENTINEL = "Aadhaar-Ramesh-Kumar"


class EncryptExistingFilesTests(TestCase):
    def setUp(self):
        self.legacy = Path(tempfile.mkdtemp(prefix="crm-legacy-"))
        self.private = Path(tempfile.mkdtemp(prefix="crm-private-"))
        self.addCleanup(shutil.rmtree, self.legacy, True)
        self.addCleanup(shutil.rmtree, self.private, True)
        override = override_settings(LEGACY_MEDIA_ROOT=str(self.legacy), MEDIA_ROOT=str(self.private))
        override.enable()
        self.addCleanup(override.disable)
        self.present = f"organization_logos/2026/10/{SENTINEL}.png"
        self.missing = f"organization_logos/2026/10/{SENTINEL}-missing.png"
        (self.legacy / self.present).parent.mkdir(parents=True)
        (self.legacy / self.present).write_bytes(SAMPLE_PNG)
        (self.legacy / "orphans").mkdir()
        (self.legacy / "orphans" / f"{SENTINEL}.pdf").write_bytes(SAMPLE_PDF)
        for slug, name in (("enc-a", self.present), ("enc-b", self.missing)):
            organization = Organization.objects.create(name=slug, slug=slug)
            OrganizationSettings.objects.create(organization=organization, company_name=slug, company_logo=name)

    def run_command(self, *args):
        out = io.StringIO()
        call_command("encrypt_existing_files", *args, stdout=out, stderr=out)
        text = out.getvalue()
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn(str(self.legacy), text)
        return text

    def counts(self, text, prefix):
        line = next(row for row in text.splitlines() if row.startswith(prefix + ":"))
        return dict(pair.split("=") for pair in line.split(":", 1)[1].split())

    def test_dry_run_changes_nothing_and_reports_counts(self):
        text = self.run_command("--dry-run")
        self.assertEqual(self.counts(text, FIELD), {"encrypted": "0", "to_encrypt": "1", "already_encrypted": "0", "missing": "1", "conflict": "0"})
        self.assertIn("orphans (files in the legacy folder that no record references): 1", text)
        self.assertEqual([path for path in self.private.rglob("*") if path.is_file()], [])
        self.assertEqual((self.legacy / self.present).read_bytes(), SAMPLE_PNG)

    def test_apply_encrypts_verifies_keeps_the_original_and_is_idempotent(self):
        first = self.run_command("--apply")
        self.assertEqual(self.counts(first, FIELD)["encrypted"], "1")
        self.assertEqual(self.counts(first, FIELD)["missing"], "1")
        self.assertTrue((self.private / self.present).read_bytes().startswith(MAGIC))
        with default_storage.open(self.present) as handle:
            self.assertEqual(handle.read(), SAMPLE_PNG)
        self.assertEqual((self.legacy / self.present).read_bytes(), SAMPLE_PNG)
        self.assertIn("originals deleted: 0", first)
        second = self.run_command("--apply")
        self.assertEqual(self.counts(second, FIELD)["encrypted"], "0")
        self.assertEqual(self.counts(second, FIELD)["already_encrypted"], "1")

    def test_delete_originals_removes_only_verified_originals(self):
        text = self.run_command("--apply", "--delete-originals")
        self.assertIn("originals deleted: 1", text)
        self.assertFalse((self.legacy / self.present).exists())
        self.assertTrue((self.legacy / "orphans" / f"{SENTINEL}.pdf").exists())
        with default_storage.open(self.present) as handle:
            self.assertEqual(handle.read(), SAMPLE_PNG)

    def test_a_conflicting_destination_is_left_alone(self):
        (self.private / self.present).parent.mkdir(parents=True)
        (self.private / self.present).write_bytes(SAMPLE_PNG)
        text = self.run_command("--apply", "--delete-originals")
        self.assertEqual(self.counts(text, FIELD)["conflict"], "1")
        self.assertEqual((self.private / self.present).read_bytes(), SAMPLE_PNG)
        self.assertTrue((self.legacy / self.present).exists())

    def test_argument_rules(self):
        for args in ((), ("--dry-run", "--apply"), ("--dry-run", "--delete-originals")):
            with self.subTest(args=args), self.assertRaises(CommandError):
                call_command("encrypt_existing_files", *args, stdout=io.StringIO(), stderr=io.StringIO())

    def test_the_legacy_and_private_folders_must_differ(self):
        with override_settings(LEGACY_MEDIA_ROOT=str(self.private)), self.assertRaises(CommandError):
            call_command("encrypt_existing_files", "--dry-run", stdout=io.StringIO())
