"""GNFR-08 / G-4 / NFR-P12-01: stored files are AES-256-GCM ciphertext; nothing is public."""
import base64
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from core.crypto import MAGIC, OVERHEAD, FileIntegrityError, decode_file_key
from core.files import private_file_response
from core.storage import EncryptedFileSystemStorage
from core.tests.samples import SAMPLE_PDF


def new_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class EncryptedStorageTests(SimpleTestCase):
    def save(self, content=SAMPLE_PDF, name="storage-tests/sample.pdf"):
        name = default_storage.save(name, ContentFile(content))
        self.addCleanup(default_storage.delete, name)
        return name

    def raw(self, name):
        return (Path(settings.MEDIA_ROOT) / name).read_bytes()

    def test_it_is_the_default_storage(self):
        self.assertIsInstance(default_storage, EncryptedFileSystemStorage)

    def test_bytes_on_disk_are_ciphertext_and_open_returns_the_original(self):
        name = self.save()
        raw = self.raw(name)
        self.assertTrue(raw.startswith(MAGIC))
        self.assertNotIn(b"%PDF", raw)
        self.assertEqual(len(raw), len(SAMPLE_PDF) + OVERHEAD)
        with default_storage.open(name) as handle:
            self.assertEqual(handle.read(), SAMPLE_PDF)

    def test_a_partly_read_upload_is_saved_whole(self):
        upload = SimpleUploadedFile("scan.pdf", SAMPLE_PDF)
        upload.read(4)
        name = default_storage.save("storage-tests/upload.pdf", upload)
        self.addCleanup(default_storage.delete, name)
        with default_storage.open(name) as handle:
            self.assertEqual(handle.read(), SAMPLE_PDF)

    def test_each_save_uses_a_fresh_nonce(self):
        self.assertNotEqual(self.raw(self.save()), self.raw(self.save()))

    def test_size_is_the_plaintext_size(self):
        self.assertEqual(default_storage.size(self.save()), len(SAMPLE_PDF))

    def test_nothing_has_a_public_url(self):
        self.assertIsNone(default_storage.url(self.save()))

    def test_files_cannot_be_opened_for_writing(self):
        name = self.save()
        for mode in ("wb", "ab", "r+b"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                default_storage.open(name, mode)

    def test_tampered_plaintext_or_wrong_key_files_are_rejected(self):
        name = self.save()
        tampered = bytearray(self.raw(name))
        tampered[-1] ^= 1
        (Path(settings.MEDIA_ROOT) / name).write_bytes(bytes(tampered))
        with self.assertRaises(FileIntegrityError):
            default_storage.open(name)
        plain = self.save()
        (Path(settings.MEDIA_ROOT) / plain).write_bytes(SAMPLE_PDF)
        with self.assertRaises(FileIntegrityError):
            default_storage.open(plain)
        other = self.save()
        with override_settings(FILE_ENCRYPTION_KEY=new_key()), self.assertRaises(FileIntegrityError):
            default_storage.open(other)

    def test_a_missing_key_stops_saving_and_opening(self):
        name = self.save()
        with override_settings(FILE_ENCRYPTION_KEY=""):
            for action in (lambda: default_storage.save("storage-tests/x.pdf", ContentFile(SAMPLE_PDF)),
                           lambda: default_storage.open(name)):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    action()
                self.assertIn("FILE_ENCRYPTION_KEY", str(raised.exception))

    def test_malformed_keys_are_rejected_without_echoing_them(self):
        short = base64.urlsafe_b64encode(os.urandom(16)).decode()
        for value in ("not-a-key", short, new_key() + "!", "é" * 44):
            with self.subTest(length=len(value)):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    decode_file_key(value)
                self.assertIn("FILE_ENCRYPTION_KEY", str(raised.exception))
                self.assertNotIn(value, str(raised.exception))
        self.assertEqual(len(decode_file_key(new_key())), 32)

    def test_a_damaged_file_is_a_500_without_its_name(self):
        name = self.save(name="storage-tests/Aadhaar-Ramesh.pdf")
        (Path(settings.MEDIA_ROOT) / name).write_bytes(b"CRMENC1" + b"\x00" * 40)
        with self.assertLogs("core.files", "ERROR") as logs:
            response = private_file_response(_FieldFileLike(name), filename="Aadhaar-Ramesh.pdf")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"Ramesh", response.content)
        self.assertNotIn("Ramesh", "\n".join(logs.output))


class _FieldFileLike:
    def __init__(self, name):
        self.name = name
        self.instance = None

    def open(self, mode="rb"):
        return default_storage.open(self.name, mode)
