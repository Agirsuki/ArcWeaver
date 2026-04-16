from __future__ import annotations

"""Multipart temporary naming helpers."""

import os
import re

from ..extraction_types import FileEvidence
from ..signatures import is_archive_kind
from .models import CandidateScore


def build_name_mapping(
    *,
    root: FileEvidence,
    selected: list[CandidateScore],
    container: str,
    missing_volumes: list[str],
) -> dict[str, str]:
    """Build the temporary canonical file names used for one multipart attempt."""

    mapping: dict[str, str] = {}
    used_names: set[str] = set()
    next_index = 2
    family_name = group_family_name(root)
    naming_scheme = resolve_naming_scheme(root, container)

    root_name = canonical_volume_name(
        family_stem=family_name,
        container=container,
        naming_scheme=naming_scheme,
        volume_index=root.filename_volume_index or 1,
        is_root=True,
    )
    mapping[root.source_path] = root_name
    used_names.add(root_name.lower())

    queued_missing = [
        os.path.basename(missing_name.strip())
        for missing_name in missing_volumes
        if missing_name.strip()
    ]
    ordered_selected = order_selected_candidates(selected, naming_scheme)
    deferred: list[CandidateScore] = []

    for item in ordered_selected:
        candidate_name = _resolve_stable_candidate_name(
            item=item,
            family_name=family_name,
            container=container,
            naming_scheme=naming_scheme,
        )
        if not candidate_name or candidate_name.lower() in used_names:
            deferred.append(item)
            continue
        mapping[item.evidence.source_path] = candidate_name
        used_names.add(candidate_name.lower())
        next_index = max(next_index, _next_index_after_name(candidate_name, naming_scheme) + 1)

    for item in deferred:
        candidate_name = _resolve_candidate_name(
            item=item,
            queued_missing=queued_missing,
            family_name=family_name,
            container=container,
            naming_scheme=naming_scheme,
            next_index=next_index,
            used_names=used_names,
        )
        while candidate_name.lower() in used_names:
            candidate_name = canonical_volume_name(
                family_stem=family_name,
                container=container,
                naming_scheme=naming_scheme,
                volume_index=next_index,
                is_root=False,
            )
            next_index += 1
        mapping[item.evidence.source_path] = candidate_name
        used_names.add(candidate_name.lower())
        next_index = max(next_index, _next_index_after_name(candidate_name, naming_scheme) + 1)

    return mapping


def resolve_container(
    root: FileEvidence,
    selected: list[CandidateScore] | None = None,
) -> str:
    """Resolve the archive container to use when materializing one multipart attempt."""

    for candidate in (root.header_type, root.filename_archive_type):
        if is_archive_kind(candidate):
            return candidate.lower()

    container_votes: dict[str, int] = {}
    for item in selected or []:
        evidence = item.evidence
        for candidate, weight in (
            (evidence.header_type, 2),
            (evidence.filename_archive_type, 1),
        ):
            if not is_archive_kind(candidate):
                continue
            normalized = candidate.lower()
            container_votes[normalized] = container_votes.get(normalized, 0) + weight

    if container_votes:
        return max(container_votes.items(), key=lambda pair: (pair[1], pair[0]))[0]
    return "7z"


def resolve_naming_scheme(root: FileEvidence, container: str) -> str:
    """Choose the canonical temporary naming scheme for the current container."""

    if container == "zip":
        if root.filename_volume_index is not None and root.filename_extension == ".001":
            return "zip_numeric"
        return "zip_split"
    if container == "rar":
        return "rar_part"
    if container == "7z":
        return "7z_numeric"
    return "generic"


def canonical_volume_name(
    *,
    family_stem: str,
    container: str,
    naming_scheme: str,
    volume_index: int,
    is_root: bool,
) -> str:
    """Convert one logical slot into a canonical temporary file name."""

    safe_family = family_stem or "archive"
    if naming_scheme == "zip_split":
        if is_root:
            return f"{safe_family}.zip"
        return f"{safe_family}.z{max(volume_index - 2, 0) + 1:02d}"
    if container == "rar":
        return f"{safe_family}.part{volume_index}.rar"
    if container in {"7z", "zip"}:
        return f"{safe_family}.{container}.{volume_index:03d}"
    if is_root:
        return f"{safe_family}.{container}"
    return f"{safe_family}.{container}.{volume_index:03d}"


def group_family_name(root: FileEvidence) -> str:
    """Extract the shared family name used for one multipart group."""

    core = series_core(root.family_stem)
    return core or root.family_stem


def series_core(value: str) -> str:
    """Remove only an explicit trailing series index from a family stem."""

    normalized = value.strip()
    match = re.search(r"^(.*?)[ _.-](\d+)$", normalized)
    if not match:
        return normalized
    prefix = match.group(1).strip(" ._-")
    if not prefix:
        return normalized
    return prefix


def trailing_series_index(value: str) -> int | None:
    """Read a trailing numeric series index from a family stem."""

    match = re.search(r"(?:^|[ _.-])(\d+)$", value.strip())
    if not match:
        return None
    return int(match.group(1))


def order_selected_candidates(
    selected: list[CandidateScore],
    naming_scheme: str,
) -> list[CandidateScore]:
    """For zip split sets, prefer a stable order by trailing series index."""

    if naming_scheme != "zip_split":
        return list(selected)

    indexed = [(item, trailing_series_index(item.evidence.family_stem)) for item in selected]
    if not any(index is not None for _item, index in indexed):
        return list(selected)

    ordered = sorted(
        indexed,
        key=lambda pair: (
            pair[1] is None,
            pair[1] if pair[1] is not None else 10**9,
            -pair[0].score,
        ),
    )
    return [item for item, _index in ordered]


def _resolve_candidate_name(
    *,
    item: CandidateScore,
    queued_missing: list[str],
    family_name: str,
    container: str,
    naming_scheme: str,
    next_index: int,
    used_names: set[str],
) -> str:
    """Resolve a candidate name using missing hints only after stable slots are reserved."""

    stable_name = _resolve_stable_candidate_name(
        item=item,
        family_name=family_name,
        container=container,
        naming_scheme=naming_scheme,
    )
    if stable_name and stable_name.lower() not in used_names:
        return stable_name

    while queued_missing:
        candidate_name = queued_missing.pop(0)
        if candidate_name.lower() not in used_names:
            return candidate_name

    while True:
        candidate_name = canonical_volume_name(
            family_stem=family_name,
            container=container,
            naming_scheme=naming_scheme,
            volume_index=next_index,
            is_root=False,
        )
        next_index += 1
        if candidate_name.lower() not in used_names:
            return candidate_name


def _resolve_stable_candidate_name(
    *,
    item: CandidateScore,
    family_name: str,
    container: str,
    naming_scheme: str,
) -> str | None:
    """Infer a stable slot directly from the candidate's own filename facts."""

    if item.evidence.filename_volume_index is not None:
        return canonical_volume_name(
            family_stem=family_name,
            container=container,
            naming_scheme=naming_scheme,
            volume_index=item.evidence.filename_volume_index,
            is_root=False,
        )

    if naming_scheme == "zip_split":
        series_index = trailing_series_index(item.evidence.family_stem)
        if series_index is not None:
            return canonical_volume_name(
                family_stem=family_name,
                container=container,
                naming_scheme=naming_scheme,
                volume_index=series_index + 1,
                is_root=False,
            )

    return None


def _next_index_after_name(candidate_name: str, naming_scheme: str) -> int:
    """Infer the next available slot index after an already assigned canonical name."""

    lowered = candidate_name.lower()
    if naming_scheme == "zip_split":
        match = re.search(r"\.z(\d{2})$", lowered)
        if not match:
            return 1
        return int(match.group(1)) + 1
    match = re.search(r"\.(\d{3})$", lowered)
    if match:
        return int(match.group(1))
    match = re.search(r"\.part(\d+)\.rar$", lowered)
    if match:
        return int(match.group(1))
    return 1
