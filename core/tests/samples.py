"""Smallest byte strings for TASK-SEC-001 / G-4 content checks."""

SAMPLE_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
SAMPLE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
SAMPLE_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
SAMPLE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 22
SAMPLE_MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 28
SAMPLE_AAC = b"\xff\xf1\x50\x80" + b"\x00" * 28
SAMPLE_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20
SAMPLE_M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 16

FORGED_HTML = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
FORGED_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
FORGED_EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 16
HEIC_IMAGE = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"\x00" * 16
