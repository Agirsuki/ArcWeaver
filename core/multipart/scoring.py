from __future__ import annotations

"""Scoring helpers used by multipart root solving."""

import os

from ..extraction_types import FileEvidence
from ..family import (
    ordered_token_prefix_similarity,
    smaller_numeric_first_difference_score,
    weighted_token_overlap_ratio,
)
from ..workflow.state import PipelineState
from .models import BootstrapPolicy, CandidateScore, RootPriorityScore, ScoreBreakdown, ScoreComponent
from .naming import series_core
from .settings import MultipartScoringConfig


def build_scored_candidates(
    *,
    state: PipelineState,
    root: FileEvidence,
    scoring_config: MultipartScoringConfig,
) -> list[CandidateScore]:
    """Score all currently available multipart candidates for one root task."""

    candidates: list[CandidateScore] = []
    root_dir = os.path.dirname(root.source_path)
    weights = scoring_config.candidate_weights

    for evidence in {
        **state.unresolved_candidates,
        **state.root_candidates,
    }.values():
        if evidence.source_path == root.source_path:
            continue

        components: list[ScoreComponent] = []

        _append_component(
            components,
            name="ordered_token_prefix_similarity",
            weight=weights.ordered_token_prefix_similarity,
            raw_value=ordered_token_prefix_similarity(root.family_tokens, evidence.family_tokens),
            detail=f"{root.family_tokens} <-> {evidence.family_tokens}",
        )
        _append_component(
            components,
            name="weighted_token_overlap",
            weight=weights.weighted_token_overlap,
            raw_value=weighted_token_overlap_ratio(root.family_tokens, evidence.family_tokens),
            detail=f"{root.family_tokens} <-> {evidence.family_tokens}",
        )
        _append_component(
            components,
            name="smaller_numeric_first_difference",
            weight=weights.smaller_numeric_first_difference,
            raw_value=smaller_numeric_first_difference_score(
                root.family_tokens,
                evidence.family_tokens,
            ),
            detail=f"{root.family_tokens} -> {evidence.family_tokens}",
        )
        _append_boolean_component(
            components,
            name="exact_normalized_family",
            weight=weights.exact_normalized_family,
            condition=root.normalized_family == evidence.normalized_family,
            detail=f"{root.normalized_family} == {evidence.normalized_family}",
        )
        _append_boolean_component(
            components,
            name="same_series_core",
            weight=weights.same_series_core,
            condition=root.family_core == evidence.family_core,
            detail=f"{root.family_core} == {evidence.family_core}",
        )
        _append_boolean_component(
            components,
            name="same_digit_tokens",
            weight=weights.same_digit_tokens,
            condition=bool(root.digit_tokens) and root.digit_tokens == evidence.digit_tokens,
            detail=f"{root.digit_tokens} == {evidence.digit_tokens}",
        )
        _append_boolean_component(
            components,
            name="same_archive_type",
            weight=weights.same_archive_type,
            condition=bool(root.filename_archive_type)
            and evidence.filename_archive_type == root.filename_archive_type,
            detail=f"{root.filename_archive_type} == {evidence.filename_archive_type}",
        )
        _append_boolean_component(
            components,
            name="same_header_type",
            weight=weights.same_header_type,
            condition=bool(root.header_type) and evidence.header_type == root.header_type,
            detail=f"{root.header_type} == {evidence.header_type}",
        )
        _append_boolean_component(
            components,
            name="same_directory",
            weight=weights.same_directory,
            condition=os.path.dirname(evidence.source_path) == root_dir,
            detail=f"{os.path.dirname(evidence.source_path)} == {root_dir}",
        )
        _append_boolean_component(
            components,
            name="same_size",
            weight=weights.same_size,
            condition=bool(root.size_bytes) and evidence.size_bytes == root.size_bytes,
            detail=f"{root.size_bytes} == {evidence.size_bytes}",
        )
        _append_boolean_component(
            components,
            name="has_volume_index",
            weight=weights.has_volume_index,
            condition=evidence.filename_volume_index is not None,
            detail=f"volume_index={evidence.filename_volume_index}",
        )
        _append_boolean_component(
            components,
            name="archive_header_mismatch_penalty",
            weight=-weights.archive_header_mismatch_penalty,
            condition=(
                evidence.file_kind == "archive"
                and bool(root.header_type)
                and bool(evidence.header_type)
                and evidence.header_type != root.header_type
            ),
            detail=f"{root.header_type} != {evidence.header_type}",
        )

        breakdown = finalize_breakdown(components)
        candidates.append(
            CandidateScore(
                evidence=evidence,
                score=breakdown.total,
                base_score=breakdown.total,
                bonus_score=0.0,
                base_components=breakdown.components,
                bonus_components=(),
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates


def pick_bootstrap_candidates(
    *,
    unresolved_count: int,
    root_count: int,
    candidates: list[CandidateScore],
    missing_volumes: list[str],
    scoring_config: MultipartScoringConfig,
) -> tuple[list[CandidateScore], BootstrapPolicy | None]:
    """Pick an initial high-confidence batch after the first missing-volume reply."""

    if not candidates:
        return [], None

    rescored_candidates = [
        apply_missing_volume_bonus(
            candidate,
            missing_volumes=missing_volumes,
            scoring_config=scoring_config,
        )
        for candidate in candidates
    ]
    rescored_candidates.sort(key=lambda item: item.score, reverse=True)
    policy = build_bootstrap_policy(
        unresolved_count=unresolved_count,
        root_count=root_count,
        candidates=rescored_candidates,
        scoring_config=scoring_config,
    )

    bootstrap: list[CandidateScore] = []
    for candidate in rescored_candidates:
        if len(bootstrap) >= policy.candidate_cap:
            continue
        if candidate.score < policy.min_score:
            continue
        if policy.leader_score - candidate.score > policy.max_score_gap:
            continue
        bootstrap.append(candidate)
    return bootstrap, policy


def pick_next_candidate(
    *,
    root: FileEvidence,
    candidates: list[CandidateScore],
    selected: list[CandidateScore],
    excluded: set[str],
    missing_volumes: list[str],
    scoring_config: MultipartScoringConfig,
) -> CandidateScore | None:
    """Pick the next best candidate in the current solving context."""

    best: CandidateScore | None = None
    for candidate in preferred_candidates(root, candidates, selected, excluded):
        current = apply_missing_volume_bonus(
            candidate,
            missing_volumes=missing_volumes,
            scoring_config=scoring_config,
        )
        if best is None or current.score > best.score:
            best = current
    return best


def build_bootstrap_policy(
    *,
    unresolved_count: int,
    root_count: int,
    candidates: list[CandidateScore],
    scoring_config: MultipartScoringConfig,
) -> BootstrapPolicy:
    """Build the bootstrap thresholds from the current unresolved candidate pool."""

    scores = [candidate.score for candidate in candidates]
    leader_score = scores[0]
    max_score = scores[0]
    min_score = scores[-1]
    mean_score = sum(scores) / len(scores)
    root_divisor = max(root_count, 1)
    raw_cap = unresolved_count // root_divisor
    candidate_cap = max(1, raw_cap)
    score_gap = (max_score - min_score) / max(1, unresolved_count)
    return BootstrapPolicy(
        mean_score=mean_score,
        leader_score=leader_score,
        min_score=max(mean_score, scoring_config.thresholds.bootstrap_min_score),
        max_score_gap=score_gap,
        candidate_cap=candidate_cap,
        unresolved_count=unresolved_count,
        root_count=root_count,
    )


def apply_missing_volume_bonus(
    candidate: CandidateScore,
    *,
    missing_volumes: list[str],
    scoring_config: MultipartScoringConfig,
) -> CandidateScore:
    """Apply missing-volume feedback on top of the base candidate score."""

    breakdown = build_missing_volume_bonus_breakdown(
        candidate.evidence,
        missing_volumes=missing_volumes,
        scoring_config=scoring_config,
    )
    return CandidateScore(
        evidence=candidate.evidence,
        score=candidate.base_score + breakdown.total,
        base_score=candidate.base_score,
        bonus_score=breakdown.total,
        base_components=candidate.base_components,
        bonus_components=breakdown.components,
    )


def build_root_priority_scores(
    roots: list[FileEvidence],
    scoring_config: MultipartScoringConfig,
) -> list[RootPriorityScore]:
    """Score all root candidates so the solver can process them in a stable order."""

    scored = [root_priority(evidence, scoring_config) for evidence in roots]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def root_priority(
    evidence: FileEvidence,
    scoring_config: MultipartScoringConfig,
) -> RootPriorityScore:
    """Compute the solve priority of one root candidate."""

    weights = scoring_config.root_priority_weights
    components: list[ScoreComponent] = []
    archive_signature_weight = _archive_signature_weight(evidence, scoring_config)
    _append_boolean_component(
        components,
        name="filename_is_root",
        weight=weights.filename_is_root,
        condition=evidence.filename_is_root,
        detail=f"filename_is_root={evidence.filename_is_root}",
    )
    _append_boolean_component(
        components,
        name="archive_signature",
        weight=archive_signature_weight,
        condition=evidence.file_kind == "archive",
        detail=f"file_kind={evidence.file_kind}, header_type={evidence.header_type}",
    )
    _append_boolean_component(
        components,
        name="missing_volume_feedback",
        weight=weights.missing_volume_feedback,
        condition=bool(evidence.last_missing_volume_names),
        detail=f"missing={list(evidence.last_missing_volume_names)}",
    )
    _append_boolean_component(
        components,
        name="has_header_type",
        weight=weights.has_header_type,
        condition=bool(evidence.header_type),
        detail=f"header_type={evidence.header_type}",
    )
    _append_boolean_component(
        components,
        name="filename_archive_without_header",
        weight=weights.filename_archive_without_header,
        condition=bool(evidence.filename_archive_type) and not evidence.header_type,
        detail=f"filename_archive_type={evidence.filename_archive_type}",
    )
    breakdown = finalize_breakdown(components)
    return RootPriorityScore(
        evidence=evidence,
        score=breakdown.total,
        components=breakdown.components,
    )


def _archive_signature_weight(
    evidence: FileEvidence,
    scoring_config: MultipartScoringConfig,
) -> float:
    """Return the root-priority archive-signature weight for the current file kind."""

    if (evidence.header_type or "").lower() == "zip":
        return scoring_config.root_priority_weights.archive_signature_zip
    return scoring_config.root_priority_weights.archive_signature


def preferred_candidates(
    root: FileEvidence,
    candidates: list[CandidateScore],
    selected: list[CandidateScore],
    excluded: set[str],
) -> list[CandidateScore]:
    """Filter out selected and excluded candidates for the current root task."""

    remaining = [
        candidate
        for candidate in candidates
        if candidate.evidence.source_path not in excluded
        and all(
            item.evidence.source_path != candidate.evidence.source_path
            for item in selected
        )
    ]
    if not remaining:
        return []

    reference_core = series_core(root.family_stem)
    same_core = [
        candidate
        for candidate in remaining
        if candidate.evidence.family_core == root.family_core
    ]
    return same_core or remaining


def build_missing_volume_bonus_breakdown(
    evidence: FileEvidence,
    *,
    missing_volumes: list[str],
    scoring_config: MultipartScoringConfig,
) -> ScoreBreakdown:
    """Score a candidate against the latest missing-volume feedback."""

    if not missing_volumes:
        return ScoreBreakdown()

    weights = scoring_config.missing_volume_weights
    components: list[ScoreComponent] = []
    for missing_name in missing_volumes:
        missing_family = build_family_identity(missing_name)
        _append_boolean_component(
            components,
            name="missing.exact_normalized_family",
            weight=weights.exact_normalized_family,
            condition=evidence.normalized_family == missing_family.normalized_family,
            detail=f"{evidence.normalized_family} == {missing_family.normalized_family} from {missing_name}",
        )
        _append_boolean_component(
            components,
            name="missing.shared_token_overlap",
            weight=weights.shared_token_overlap,
            condition=bool(evidence.family_tokens)
            and bool(set(evidence.family_tokens) & set(missing_family.tokens))
            and evidence.normalized_family != missing_family.normalized_family,
            detail=f"{evidence.family_tokens} <-> {missing_family.tokens} from {missing_name}",
        )
        _append_boolean_component(
            components,
            name="missing.same_volume_index",
            weight=weights.same_volume_index,
            condition=(
                evidence.filename_volume_index is not None
                and missing_family.archive_hint.volume_index is not None
                and evidence.filename_volume_index == missing_family.archive_hint.volume_index
            ),
            detail=(
                f"{evidence.filename_volume_index} == "
                f"{missing_family.archive_hint.volume_index} from {missing_name}"
            ),
        )
    return finalize_breakdown(components)


def finalize_breakdown(components: list[ScoreComponent]) -> ScoreBreakdown:
    """Freeze component details and compute the final total."""

    return ScoreBreakdown(
        total=sum(component.contribution for component in components),
        components=tuple(components),
    )


def _append_component(
    components: list[ScoreComponent],
    *,
    name: str,
    weight: float,
    raw_value: float,
    detail: str,
) -> None:
    """Append a weighted component that scales with a raw numeric value."""

    contribution = raw_value * weight
    components.append(
        ScoreComponent(
            name=name,
            weight=weight,
            raw_value=raw_value,
            contribution=contribution,
            detail=detail,
        )
    )


def _append_boolean_component(
    components: list[ScoreComponent],
    *,
    name: str,
    weight: float,
    condition: bool,
    detail: str,
) -> None:
    """Append a binary component that either contributes its full weight or zero."""

    raw_value = 1.0 if condition else 0.0
    _append_component(
        components,
        name=name,
        weight=weight,
        raw_value=raw_value,
        detail=detail,
    )
