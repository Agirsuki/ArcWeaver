from __future__ import annotations

"""Multipart scoring configuration loaded from JSON."""

from dataclasses import dataclass, field
import json
from functools import lru_cache
from typing import Any

from ..runtime_paths import get_default_multipart_scoring_path


@dataclass(slots=True)
class CandidateScoreWeights:
    """Weights used when scoring candidate continuation volumes."""

    ordered_token_prefix_similarity: float = 80.0
    weighted_token_overlap: float = 36.0
    smaller_numeric_first_difference: float = 20.0
    exact_normalized_family: float = 100.0
    same_series_core: float = 70.0
    same_digit_tokens: float = 18.0
    same_archive_type: float = 16.0
    same_header_type: float = 14.0
    same_directory: float = 10.0
    same_size: float = 8.0
    has_volume_index: float = 4.0
    archive_header_mismatch_penalty: float = 12.0


@dataclass(slots=True)
class MissingVolumeWeights:
    """Extra weights applied when 7-Zip already reported missing names."""

    exact_normalized_family: float = 120.0
    shared_token_overlap: float = 32.0
    same_volume_index: float = 48.0


@dataclass(slots=True)
class RootPriorityWeights:
    """Weights used to decide which root candidate should be solved first."""

    filename_is_root: float = 50.0
    archive_signature: float = 30.0
    archive_signature_zip: float = 10.0
    missing_volume_feedback: float = 20.0
    has_header_type: float = 10.0
    filename_archive_without_header: float = 18.0


@dataclass(slots=True)
class MultipartThresholds:
    """Threshold values used by multipart heuristics."""

    bootstrap_min_score: float = 35.0


@dataclass(slots=True)
class MultipartScoringConfig:
    """Container for all multipart scoring sections."""

    candidate_weights: CandidateScoreWeights = field(default_factory=CandidateScoreWeights)
    missing_volume_weights: MissingVolumeWeights = field(default_factory=MissingVolumeWeights)
    root_priority_weights: RootPriorityWeights = field(default_factory=RootPriorityWeights)
    thresholds: MultipartThresholds = field(default_factory=MultipartThresholds)


@lru_cache(maxsize=4)
def load_multipart_scoring_config(config_path: str | None = None) -> MultipartScoringConfig:
    """Load multipart scoring config from disk and cache the parsed result."""

    path = config_path or get_default_multipart_scoring_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return MultipartScoringConfig()

    return MultipartScoringConfig(
        candidate_weights=_load_section(CandidateScoreWeights, raw.get("candidate_weights")),
        missing_volume_weights=_load_section(MissingVolumeWeights, raw.get("missing_volume_weights")),
        root_priority_weights=_load_section(RootPriorityWeights, raw.get("root_priority_weights")),
        thresholds=_load_section(MultipartThresholds, raw.get("thresholds")),
    )


def _load_section(cls, raw: Any):
    """Load one scoring section and coerce all configured values to floats."""

    if not isinstance(raw, dict):
        return cls()
    defaults = cls()
    values = {}
    for field_name in defaults.__dataclass_fields__:
        value = raw.get(field_name, getattr(defaults, field_name))
        values[field_name] = float(value)
    return cls(**values)
