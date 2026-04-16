from __future__ import annotations

"""Helpers for carving embedded archives out of polyglot files."""

from dataclasses import dataclass
import os

from .archive_backend import list_archive_type


_ARCHIVE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"),
    (b"Rar!\x1A\x07\x00", "rar"),
    (b"Rar!\x1A\x07\x01\x00", "rar"),
    (b"7z\xBC\xAF\x27\x1C", "7z"),
)


@dataclass(slots=True)
class PolyglotHit:
    """A carved archive candidate discovered inside a non-archive file."""

    archive_type: str
    offset: int
    carved_path: str


def carve_hidden_archive(
    file_path: str,
    working_dir: str,
    *,
    passwords: list[str],
    seven_zip_path: str | None = None,
    max_scan_bytes: int | None = None,
) -> PolyglotHit | None:
    """Scan for known archive signatures beyond byte zero and carve a tail hit."""

    os.makedirs(working_dir, exist_ok=True)
    file_size = os.path.getsize(file_path)
    scan_limit = file_size if not max_scan_bytes else min(file_size, max_scan_bytes)

    with open(file_path, "rb") as handle:
        payload = handle.read(scan_limit)

    for signature, archive_type in _ARCHIVE_SIGNATURES:
        start = 1
        while True:
            offset = payload.find(signature, start)
            if offset < 0:
                break
            carved_path = os.path.join(
                working_dir,
                f"{os.path.basename(file_path)}.__polyglot_{offset}.{archive_type}",
            )
            _carve_file(file_path, carved_path, offset)
            detected = list_archive_type(
                carved_path,
                passwords=passwords,
                seven_zip_path=seven_zip_path,
            )
            if detected or archive_type:
                return PolyglotHit(
                    archive_type=detected or archive_type,
                    offset=offset,
                    carved_path=carved_path,
                )
            _remove_if_exists(carved_path)
            start = offset + 1

    return None


def _carve_file(source_path: str, output_path: str, offset: int) -> None:
    """Copy the file tail starting at the discovered embedded archive offset."""

    with open(source_path, "rb") as source, open(output_path, "wb") as output:
        source.seek(offset)
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def _remove_if_exists(path: str) -> None:
    """Best-effort cleanup for temporary carved files."""

    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
