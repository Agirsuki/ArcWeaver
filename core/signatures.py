from __future__ import annotations

"""Lightweight file signature detection used before invoking 7-Zip."""

from dataclasses import dataclass
import os


ARCHIVE_KINDS = {"7z", "zip", "rar", "gz", "bz2", "xz", "zst", "tar"}


@dataclass(frozen=True, slots=True)
class SignatureMatch:
    """Detected file type and the category it belongs to."""

    kind: str
    category: str
    extension: str


_HEADER_SIGNATURES: tuple[tuple[bytes, SignatureMatch], ...] = (
    (b"7z\xbc\xaf\x27\x1c", SignatureMatch("7z", "archive", ".7z")),
    (b"Rar!\x1a\x07\x00", SignatureMatch("rar", "archive", ".rar")),
    (b"Rar!\x1a\x07\x01\x00", SignatureMatch("rar", "archive", ".rar")),
    (b"PK\x03\x04", SignatureMatch("zip", "archive", ".zip")),
    (b"PK\x05\x06", SignatureMatch("zip", "archive", ".zip")),
    (b"PK\x07\x08", SignatureMatch("zip", "archive", ".zip")),
    (b"\x1f\x8b", SignatureMatch("gz", "archive", ".gz")),
    (b"BZh", SignatureMatch("bz2", "archive", ".bz2")),
    (b"\xfd7zXZ\x00", SignatureMatch("xz", "archive", ".xz")),
    (b"\x28\xb5\x2f\xfd", SignatureMatch("zst", "archive", ".zst")),
    (b"%PDF-", SignatureMatch("pdf", "non_archive", ".pdf")),
    (b"\x89PNG\r\n\x1a\n", SignatureMatch("png", "non_archive", ".png")),
    (b"\xff\xd8\xff", SignatureMatch("jpg", "non_archive", ".jpg")),
    (b"GIF87a", SignatureMatch("gif", "non_archive", ".gif")),
    (b"GIF89a", SignatureMatch("gif", "non_archive", ".gif")),
    (b"RIFF", SignatureMatch("wav", "non_archive", ".wav")),
    (b"fLaC", SignatureMatch("flac", "non_archive", ".flac")),
    (b"ID3", SignatureMatch("mp3", "non_archive", ".mp3")),
    (b"OggS", SignatureMatch("ogg", "non_archive", ".ogg")),
    (b"\x1a\x45\xdf\xa3", SignatureMatch("mkv", "non_archive", ".mkv")),
)


_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".log",
    ".csv",
    ".xml",
    ".html",
    ".htm",
}


def detect_file_signature(file_path: str) -> SignatureMatch | None:
    """Read a short header and infer a likely file type."""

    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, "rb") as handle:
            header = handle.read(4096)
            if len(header) < 4:
                return None

            for signature, match in _HEADER_SIGNATURES:
                if header.startswith(signature):
                    if match.kind == "wav" and header[8:12] != b"WAVE":
                        continue
                    return match

            if len(header) >= 12 and header[4:8] == b"ftyp":
                return SignatureMatch("mp4", "non_archive", ".mp4")

            if len(header) >= 265 and header[257:262] == b"ustar":
                return SignatureMatch("tar", "archive", ".tar")

            if _looks_like_text(header, file_path):
                return SignatureMatch("txt", "non_archive", ".txt")
    except OSError:
        return None

    return None


def is_archive_kind(kind: str | None) -> bool:
    """Return whether a detected kind should be treated as an archive."""

    return bool(kind and kind.lower() in ARCHIVE_KINDS)


def _looks_like_text(header: bytes, file_path: str) -> bool:
    """Treat common text files as final content instead of unresolved noise."""

    extension = os.path.splitext(file_path)[1].lower()
    if extension not in _TEXT_EXTENSIONS:
        return False
    if b"\x00" in header:
        return False

    try:
        decoded = header.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded = header.decode("utf-16")
        except UnicodeDecodeError:
            return False

    printable_chars = sum(1 for char in decoded if char.isprintable() or char in "\r\n\t")
    return printable_chars >= max(1, int(len(decoded) * 0.9))
