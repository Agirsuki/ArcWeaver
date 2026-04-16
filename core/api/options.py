from __future__ import annotations

"""Normalization helpers for the public API options."""

from dataclasses import asdict, fields
from typing import Any, Mapping

from .models import DeleteOptions, ExtractOptions


def default_extract_options() -> ExtractOptions:
    """Return a fresh default extraction options object."""

    return ExtractOptions()


def default_delete_options() -> DeleteOptions:
    """Return a fresh default cleanup options object."""

    return DeleteOptions()


def normalize_extract_options(
    options: ExtractOptions | Mapping[str, Any] | None,
) -> ExtractOptions:
    """Normalize external extraction options into a stable internal object."""

    if options is None:
        normalized = ExtractOptions()
    elif isinstance(options, ExtractOptions):
        normalized = ExtractOptions(**asdict(options))
    elif isinstance(options, Mapping):
        normalized = ExtractOptions(**_filter_dataclass_kwargs(ExtractOptions, options))
    else:
        raise TypeError("options must be ExtractOptions, mapping, or None")

    normalized.passwords = _normalize_passwords(normalized.passwords)
    normalized.max_depth = max(1, int(normalized.max_depth))
    normalized.workspace_suffix_length = max(4, int(normalized.workspace_suffix_length))
    return normalized


def normalize_delete_options(
    options: DeleteOptions | Mapping[str, Any] | None,
) -> DeleteOptions:
    """Normalize cleanup options into a stable internal object."""

    if options is None:
        return DeleteOptions()
    if isinstance(options, DeleteOptions):
        return DeleteOptions(**asdict(options))
    if isinstance(options, Mapping):
        return DeleteOptions(**_filter_dataclass_kwargs(DeleteOptions, options))
    raise TypeError("options must be DeleteOptions, mapping, or None")


def _normalize_passwords(passwords: list[str]) -> list[str]:
    """Drop blanks while preserving password order."""

    ordered: list[str] = []
    for password in passwords:
        if not isinstance(password, str):
            continue
        value = password.strip()
        if value and value not in ordered:
            ordered.append(value)
    return ordered


def _filter_dataclass_kwargs(cls, values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only fields declared on the target dataclass."""

    field_names = {item.name for item in fields(cls)}
    return {key: value for key, value in values.items() if key in field_names}
