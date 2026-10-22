"""TASK-SEC-001 / G-4 / NFR-P12-01: content checks and safe downloads."""

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.fields.files import FieldFile
from django.http import Http404
from django.test import SimpleTestCase

from core.files import AUDIO_KINDS, DOCUMENT_KINDS, FILE_TYPES, IMAGE_KINDS, detect_file_type, private_file_response, validate_upload
from core.tests.samples import FORGED_EXE, FORGED_HTML, FORGED_SVG, HEIC_IMAGE, SAMPLE_AAC, SAMPLE_JPEG, SAMPLE_M4A, SAMPLE_MP3, SAMPLE_MP3_FRAME, SAMPLE_PDF, SAMPLE_PNG, SAMPLE_WAV
from documents.models import CustomerDocument

MB = 1024 * 1024


def upload(name, content, content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class DetectFileTypeTests(SimpleTestCase):
    def test_each_supported_type_is_detected_from_its_bytes(self):
        cases = {"pdf": SAMPLE_PDF, "jpeg": SAMPLE_JPEG, "png": SAMPLE_PNG, "mp3": SAMPLE_MP3, "wav": SAMPLE_WAV, "m4a": SAMPLE_M4A, "aac": SAMPLE_AAC}
        for kind, content in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(detect_file_type(content), kind)
        self.assertEqual(detect_file_type(SAMPLE_MP3_FRAME), "mp3")

    def test_adts_and_mpeg_frames_are_told_apart_by_the_layer_bits(self):
        self.assertEqual(detect_file_type(b"\xff\xf9\x50\x80" + b"\x00" * 12), "aac")
        self.assertEqual(detect_file_type(b"\xff\xf3\x90\x64" + b"\x00" * 12), "mp3")

    def test_unknown_or_forged_content_is_not_detected(self):
        reserved_version = b"\xff\xea\x90\x64" + b"\x00" * 12
        bad_bitrate = b"\xff\xfb\xf0\x64" + b"\x00" * 12
        for content in (FORGED_HTML, FORGED_SVG, FORGED_EXE, HEIC_IMAGE, b"", b"%PD", reserved_version, bad_bitrate):
            with self.subTest(content=content[:8]):
                self.assertIsNone(detect_file_type(content))

    def test_mime_types(self):
        self.assertEqual(FILE_TYPES, {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png", "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac"})


class ValidateUploadTests(SimpleTestCase):
    def test_returns_the_detected_type_not_the_declared_one(self):
        file = upload("scan.pdf", SAMPLE_PNG)
        self.assertEqual(validate_upload(file, kinds=DOCUMENT_KINDS, max_bytes=MB), "image/png")
        self.assertEqual(file.read(), SAMPLE_PNG)

    def test_forged_files_are_rejected_under_the_field_name(self):
        cases = [("invoice.pdf", FORGED_HTML, DOCUMENT_KINDS), ("photo.png", FORGED_EXE, DOCUMENT_KINDS), ("logo.png", FORGED_SVG, IMAGE_KINDS), ("call.mp3", FORGED_HTML, AUDIO_KINDS), ("call.mp3", SAMPLE_PDF, AUDIO_KINDS)]
        for name, content, kinds in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError) as raised:
                    validate_upload(upload(name, content), kinds=kinds, max_bytes=MB, field="recording")
                self.assertEqual(list(raised.exception.message_dict), ["recording"])

    def test_messages(self):
        checks = [(None, DOCUMENT_KINDS, "A file is required."), (upload("big.pdf", FORGED_HTML + b"\x00" * MB), DOCUMENT_KINDS, "Files must be 1 MB or smaller."), (upload("x.pdf", FORGED_HTML), DOCUMENT_KINDS, "Allowed file types: PDF, JPEG, PNG."), (upload("x.mp3", FORGED_HTML), AUDIO_KINDS, "Allowed file types: MP3, WAV, M4A, AAC.")]
        for file, kinds, message in checks:
            with self.subTest(message=message):
                with self.assertRaises(ValidationError) as raised:
                    validate_upload(file, kinds=kinds, max_bytes=MB)
                self.assertEqual(raised.exception.message_dict, {"file": [message]})

    def test_field_none_raises_a_plain_message_for_serializers(self):
        with self.assertRaises(ValidationError) as raised:
            validate_upload(upload("logo.png", FORGED_SVG), kinds=IMAGE_KINDS, max_bytes=MB, field=None)
        self.assertFalse(hasattr(raised.exception, "error_dict"))
        self.assertEqual(raised.exception.messages, ["Allowed file types: JPEG, PNG."])


class PrivateFileResponseTests(SimpleTestCase):
    def test_download_is_an_attachment_with_protective_headers(self):
        response = private_file_response(ContentFile(SAMPLE_PDF), filename="Signed copy.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, SAMPLE_PDF)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="Signed copy.pdf"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_the_type_comes_from_the_bytes(self):
        for content, expected in ((SAMPLE_PNG, "image/png"), (FORGED_HTML, "application/octet-stream"), (b"document", "application/octet-stream")):
            with self.subTest(expected=expected):
                self.assertEqual(private_file_response(ContentFile(content), filename="file.pdf")["Content-Type"], expected)

    def test_unicode_and_unsafe_filenames_are_encoded(self):
        for filename in ("आधार.pdf", 'bad"\r\nX-Injected: 1.pdf'):
            disposition = private_file_response(ContentFile(SAMPLE_PDF), filename=filename)["Content-Disposition"]
            self.assertTrue(disposition.startswith("attachment; filename*=utf-8''"))
            self.assertNotIn("\n", disposition)

    def test_the_file_is_closed_once_the_response_is_built(self):
        name = default_storage.save("core-tests/closed.pdf", ContentFile(SAMPLE_PDF))
        stored = default_storage.open(name)
        response = private_file_response(stored, filename="closed.pdf")
        self.assertTrue(stored.closed)
        default_storage.delete(name)
        self.assertEqual(response.content, SAMPLE_PDF)

    def test_a_missing_file_is_a_404(self):
        missing = FieldFile(None, CustomerDocument._meta.get_field("file"), "core-tests/missing.pdf")
        with self.assertRaises(Http404):
            private_file_response(missing, filename="missing.pdf")
