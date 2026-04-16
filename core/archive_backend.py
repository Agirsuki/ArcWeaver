from __future__ import annotations

"""Low-level archive access built on top of 7-Zip."""

from dataclasses import dataclass, field
import os
import re
import subprocess

from .runtime_paths import get_default_7z_path


_MISSING_VOLUME_KEYWORDS = ("missing volume", "unexpected end of archive")
_PASSWORD_KEYWORDS = (
    "wrong password",
    "cannot open encrypted archive",
    "password is incorrect",
)
_NOT_ARCHIVE_KEYWORDS = (
    "can't open as archive",
    "cannot open as archive",
    "can not open as archive",
    "cannot open the file as [",
    "is not archive",
    "not a valid archive",
)
_CORRUPTED_KEYWORDS = ("data error", "crc failed", "headers error", "corrupt")
_IO_KEYWORDS = ("not enough space", "disk full", "access is denied", "permission denied")


@dataclass(slots=True)
class ArchiveAttemptResult:
    """Normalized result of one 7-Zip extraction attempt."""

    status: str
    archive_path: str
    output_dir: str
    used_password: str = ""
    archive_type: str | None = None
    missing_volumes: list[str] = field(default_factory=list)
    message: str = ""
    raw_output: str = ""

    @property
    def success(self) -> bool:
        """Whether the extraction attempt succeeded."""

        return self.status == "success"


def extract_archive(
    archive_path: str,
    output_dir: str,
    *,
    passwords: list[str],
    seven_zip_path: str | None = None,
) -> ArchiveAttemptResult:
    """Extract an archive and classify the 7-Zip outcome into workflow statuses."""

    resolved_7z = _resolve_7z_path(seven_zip_path)
    password_candidates = [""] + [password for password in passwords if password]
    last_password_error: ArchiveAttemptResult | None = None

    for password in _dedupe(password_candidates):
        os.makedirs(output_dir, exist_ok=True)
        command = [
            resolved_7z,
            "x",
            f"-p{password}",
            f"-o{output_dir}",
            "-y",
            archive_path,
        ]
        stdout, stderr, code = _run_command(command)
        combined = f"{stdout}\n{stderr}".strip()
        result = _classify_attempt(
            archive_path=archive_path,
            output_dir=output_dir,
            combined_output=combined,
            return_code=code,
            used_password=password,
            archive_type=_parse_archive_type(stdout),
        )
        if result.success:
            return result
        if result.status == "password_error":
            last_password_error = result
            continue
        return result

    return last_password_error or ArchiveAttemptResult(
        status="unknown_error",
        archive_path=archive_path,
        output_dir=output_dir,
        message=f"Extraction failed: {archive_path}",
    )


def list_archive_type(
    archive_path: str,
    *,
    passwords: list[str],
    seven_zip_path: str | None = None,
) -> str | None:
    """Ask 7-Zip for the detected archive type without extracting."""

    resolved_7z = _resolve_7z_path(seven_zip_path)
    for password in _dedupe([""] + [password for password in passwords if password]):
        command = [resolved_7z, "l", "-slt", f"-p{password}", archive_path]
        stdout, stderr, _code = _run_command(command)
        archive_type = _parse_archive_type(stdout)
        if archive_type:
            return archive_type
        if _contains_any(f"{stdout}\n{stderr}".lower(), _PASSWORD_KEYWORDS):
            continue
    return None


def _resolve_7z_path(seven_zip_path: str | None) -> str:
    """Resolve the effective 7-Zip executable path."""

    candidate = seven_zip_path or get_default_7z_path()
    if not os.path.exists(candidate):
        raise FileNotFoundError(f"7z executable not found: {candidate}")
    return candidate


def _run_command(command: list[str]) -> tuple[str, str, int]:
    """Run a subprocess command and decode stdout and stderr."""

    run_kwargs: dict[str, object] = {
        "capture_output": True,
        "text": False,
        "check": False,
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        run_kwargs["startupinfo"] = startupinfo
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(command, **run_kwargs)
    stdout = _decode_output(result.stdout)
    stderr = _decode_output(result.stderr)
    return stdout, stderr, result.returncode


def _decode_output(payload: bytes) -> str:
    """Decode 7-Zip output across common Windows encodings."""

    for encoding in ("utf-8", "gbk", "cp936", "cp1252"):
        try:
            return payload.decode(encoding, errors="replace")
        except Exception:
            continue
    return payload.decode(errors="replace")


def _classify_attempt(
    *,
    archive_path: str,
    output_dir: str,
    combined_output: str,
    return_code: int,
    used_password: str,
    archive_type: str | None,
) -> ArchiveAttemptResult:
    """Map raw 7-Zip output into the workflow's normalized status set."""

    lowered = combined_output.lower()
    missing_volumes = _parse_missing_volumes(combined_output)
    if return_code == 0:
        return ArchiveAttemptResult(
            status="success",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            raw_output=combined_output,
        )
    if missing_volumes or _contains_any(lowered, _MISSING_VOLUME_KEYWORDS):
        return ArchiveAttemptResult(
            status="missing_volume",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            missing_volumes=missing_volumes,
            message=f"Missing multipart volumes for: {archive_path}",
            raw_output=combined_output,
        )
    if _contains_any(lowered, _PASSWORD_KEYWORDS):
        return ArchiveAttemptResult(
            status="password_error",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            message=f"Password required or incorrect: {archive_path}",
            raw_output=combined_output,
        )
    if _contains_any(lowered, _NOT_ARCHIVE_KEYWORDS):
        return ArchiveAttemptResult(
            status="not_archive",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            message=f"File is not a valid archive: {archive_path}",
            raw_output=combined_output,
        )
    if _contains_any(lowered, _CORRUPTED_KEYWORDS):
        return ArchiveAttemptResult(
            status="corrupted",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            message=f"Archive appears corrupted: {archive_path}",
            raw_output=combined_output,
        )
    if _contains_any(lowered, _IO_KEYWORDS):
        return ArchiveAttemptResult(
            status="io_error",
            archive_path=archive_path,
            output_dir=output_dir,
            used_password=used_password,
            archive_type=archive_type,
            message=f"I/O error during extraction: {archive_path}",
            raw_output=combined_output,
        )
    return ArchiveAttemptResult(
        status="unknown_error",
        archive_path=archive_path,
        output_dir=output_dir,
        used_password=used_password,
        archive_type=archive_type,
        message=combined_output.strip() or f"Extraction failed: {archive_path}",
        raw_output=combined_output,
    )


def _parse_archive_type(stdout: str) -> str | None:
    """Extract the archive type reported by 7-Zip list output."""

    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Type = "):
            return stripped.split(" = ", 1)[1].strip().lower() or None
    return None


def _parse_missing_volumes(output: str) -> list[str]:
    """Parse missing volume names from 7-Zip diagnostics."""

    matches = re.findall(r"Missing volume\s*:\s*(.+)", output, flags=re.IGNORECASE)
    result: list[str] = []
    for match in matches:
        value = match.strip()
        if value and value not in result:
            result.append(value)
    return result


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Return whether any keyword appears in the given text."""

    return any(keyword in text for keyword in keywords)


def _dedupe(values: list[str]) -> list[str]:
    """Deduplicate values while preserving order."""

    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
