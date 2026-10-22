"""Upload content checks and safe downloads (TASK-SEC-001, Appendix G-4, NFR-P12-01)."""

import logging

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.utils.http import content_disposition_header

from .crypto import FileIntegrityError

logger = logging.getLogger(__name__)

MB = 1024 * 1024
HEADER_BYTES = 16
FILE_TYPES = {
    "pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png",
    "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac",
}
LABELS = {"pdf": "PDF", "jpeg": "JPEG", "png": "PNG", "mp3": "MP3", "wav": "WAV", "m4a": "M4A", "aac": "AAC"}
DOCUMENT_KINDS = ("pdf", "jpeg", "png")
IMAGE_KINDS = ("jpeg", "png")
AUDIO_KINDS = ("mp3", "wav", "m4a", "aac")
IMAGE_MAX_BYTES = 10 * MB
M4A_BRANDS = {b"M4A ", b"M4B ", b"mp41", b"mp42", b"isom", b"iso2"}


def _is_mpeg_audio_frame(header):
    if len(header) < 3 or header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
        return False
    version, layer = (header[1] >> 3) & 0x03, (header[1] >> 1) & 0x03
    bitrate, sample_rate = header[2] >> 4, (header[2] >> 2) & 0x03
    return version != 0b01 and layer != 0b00 and bitrate != 0x0F and sample_rate != 0b11


def detect_file_type(header):
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"ID3") or _is_mpeg_audio_frame(header):
        return "mp3"
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xF6) == 0xF0:
        return "aac"
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    if header[4:8] == b"ftyp" and header[8:12] in M4A_BRANDS:
        return "m4a"
    return None


def _reject(field, message):
    raise ValidationError({field: message} if field else message)


def validate_upload(uploaded_file, *, kinds, max_bytes, field="file"):
    if not uploaded_file:
        _reject(field, "A file is required.")
    if uploaded_file.size > max_bytes:
        _reject(field, f"Files must be {max_bytes // MB} MB or smaller.")
    uploaded_file.seek(0)
    kind = detect_file_type(uploaded_file.read(HEADER_BYTES))
    uploaded_file.seek(0)
    if kind not in kinds:
        _reject(field, "Allowed file types: " + ", ".join(LABELS[k] for k in kinds) + ".")
    return FILE_TYPES[kind]


def validate_image_upload(value):
    validate_upload(value, kinds=IMAGE_KINDS, max_bytes=IMAGE_MAX_BYTES, field=None)


def private_file_response(field_file, *, filename):
    try:
        with field_file.open("rb") as handle:
            content = handle.read()
    except (FileNotFoundError, ValueError) as error:
        raise Http404("File not found.") from error
    except FileIntegrityError:
        instance = getattr(field_file, "instance", None)
        where = f"{instance._meta.label} id={instance.pk}" if instance is not None else "unknown record"
        logger.error("A stored file failed its integrity check (%s).", where)
        return JsonResponse({"detail": "The stored file could not be read."}, status=500)
    kind = detect_file_type(content[:HEADER_BYTES])
    response = HttpResponse(content, content_type=FILE_TYPES.get(kind, "application/octet-stream"))
    response["Content-Disposition"] = content_disposition_header(True, filename or "download")
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, no-store"
    return response
