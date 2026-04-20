from __future__ import annotations

"""Helpers for normalizing workflow-facing extraction settings."""

from dataclasses import fields
from typing import Any, Mapping

from .extraction_types import EmbeddedExtractionConfig


def normalize_embedded_config(
    config: EmbeddedExtractionConfig | Mapping[str, Any] | None,
) -> EmbeddedExtractionConfig:
    """Normalize arbitrary input into a stable embedded config object."""

    if config is None:
        normalized = EmbeddedExtractionConfig()
    elif isinstance(config, EmbeddedExtractionConfig):
        normalized = config
    elif isinstance(config, Mapping):
        field_names = {item.name for item in fields(EmbeddedExtractionConfig)}
        kwargs = {key: value for key, value in config.items() if key in field_names}
        normalized = EmbeddedExtractionConfig(**kwargs)
    else:
        raise TypeError("config must be EmbeddedExtractionConfig, mapping, or None")

    normalized.passwords = _normalize_passwords(normalized.passwords)
    normalized.max_depth = max(1, int(normalized.max_depth))
    normalized.multipart_bootstrap_count = max(1, int(normalized.multipart_bootstrap_count))
    normalized.multipart_max_candidates = max(
        normalized.multipart_bootstrap_count,
        int(normalized.multipart_max_candidates),
    )
    normalized.extracted_root_fast_track_file_threshold = max(
        1,
        int(normalized.extracted_root_fast_track_file_threshold),
    )
    normalized.extracted_root_fast_track_dir_threshold = max(
        1,
        int(normalized.extracted_root_fast_track_dir_threshold),
    )
    normalized.prompt_on_large_extracted_root = bool(
        normalized.prompt_on_large_extracted_root
    )
    normalized.extracted_root_threshold_mode = (
        "and"
        if str(normalized.extracted_root_threshold_mode).strip().lower() == "and"
        else "or"
    )
    normalized.extracted_root_preview_limit = max(
        0,
        int(normalized.extracted_root_preview_limit),
    )
    normalized.force_probe_extensions = tuple(
        extension.lower().lstrip(".")
        for extension in normalized.force_probe_extensions
        if isinstance(extension, str) and extension.strip()
    ) or ("zip", "7z", "rar")
    return normalized


def default_embedded_config() -> EmbeddedExtractionConfig:
    """Return the default workflow configuration."""

    return EmbeddedExtractionConfig()


def _normalize_passwords(passwords: list[str]) -> list[str]:
    """Trim, deduplicate, and preserve password order."""

    ordered: list[str] = []
    for password in passwords:
        if not isinstance(password, str):
            continue
        value = password.strip()
        if value and value not in ordered:
            ordered.append(value)
    return ordered
