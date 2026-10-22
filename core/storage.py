"""Default file storage: encrypted at rest, private, never served (Appendix G-4, NFR-P12-01)."""
import io

from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage

from .crypto import OVERHEAD, decrypt_bytes, encrypt_bytes


class EncryptedFileSystemStorage(FileSystemStorage):
    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        return super()._save(name, ContentFile(encrypt_bytes(content.read())))

    def _open(self, name, mode="rb"):
        if any(flag in mode for flag in "wax+"):
            raise ValueError("Stored files are read-only; save a new file instead.")
        with super()._open(name, "rb") as handle:
            blob = handle.read()
        # A real File (not ContentFile, whose close() is a no-op) so callers can close it.
        return File(io.BytesIO(decrypt_bytes(blob)), name=name)

    def size(self, name):
        return max(super().size(name) - OVERHEAD, 0)

    def url(self, name):
        return None
