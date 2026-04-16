from __future__ import annotations

"""多卷求解阶段。"""

import os
import shutil
from uuid import uuid4

from ..archive_backend import ArchiveAttemptResult, extract_archive
from ..extraction_types import EmbeddedExtractionConfig, ExtractionGroupResult, FileEvidence
from ..path_ops import unique_path
from ..workflow.state import PipelineState
from .models import BootstrapPolicy, CandidateScore, RootPriorityScore, ScoreComponent
from .naming import build_name_mapping, resolve_container
from .scoring import (
    build_root_priority_scores,
    build_scored_candidates,
    pick_bootstrap_candidates,
    pick_next_candidate,
)
from .settings import MultipartScoringConfig, load_multipart_scoring_config


def solve_pending_multipart(
    state: PipelineState,
    *,
    config: EmbeddedExtractionConfig,
) -> int:
    """处理当前积压的主卷候选。"""

    scoring_config = load_multipart_scoring_config()
    new_extractions = 0
    root_scores = build_root_priority_scores(list(state.root_candidates.values()), scoring_config)
    _log_root_priority_table(state, root_scores)

    for root_score in root_scores:
        root = root_score.evidence
        if root.source_path not in state.root_candidates:
            continue
        group_result = _solve_root_task(
            state=state,
            config=config,
            root=root,
            root_priority_score=root_score,
            scoring_config=scoring_config,
        )
        state.group_results.append(group_result)
        if group_result.success:
            new_extractions += 1

    return new_extractions


def _solve_root_task(
    *,
    state: PipelineState,
    config: EmbeddedExtractionConfig,
    root: FileEvidence,
    root_priority_score: RootPriorityScore,
    scoring_config: MultipartScoringConfig,
) -> ExtractionGroupResult:
    """围绕一个主卷候选做增量式组卷尝试。"""

    state.log_debug(f"[multipart] solve root {root.source_path}")
    _log_root_priority_detail(state, root_priority_score)
    all_candidates = build_scored_candidates(
        state=state,
        root=root,
        scoring_config=scoring_config,
    )
    _log_candidate_ranking(state, root, all_candidates)
    selected: list[CandidateScore] = []
    excluded: set[str] = set()
    attempted_sets: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    last_result: ArchiveAttemptResult | None = None
    bootstrapped = _should_skip_root_only_attempt(root)
    preflight_candidates = _pick_same_directory_preflight_candidates(
        state=state,
        root=root,
        candidates=all_candidates,
    )

    if preflight_candidates:
        _log_same_directory_preflight(
            state=state,
            root=root,
            selected=preflight_candidates,
        )
        selected.extend(preflight_candidates)
        bootstrapped = False

    if bootstrapped and not selected:
        bootstrap, bootstrap_policy = pick_bootstrap_candidates(
            unresolved_count=len(all_candidates),
            root_count=max(1, len(state.root_candidates)),
            candidates=all_candidates,
            missing_volumes=list(root.last_missing_volume_names),
            scoring_config=scoring_config,
        )
        if bootstrap:
            _log_bootstrap_selection(
                state=state,
                root=root,
                selected=bootstrap,
                policy=bootstrap_policy,
                missing_volumes=list(root.last_missing_volume_names),
            )
            selected.extend(bootstrap)
        else:
            bootstrapped = False

    while True:
        selection_key = (
            tuple(sorted(item.evidence.source_path for item in selected)),
            tuple(sorted(excluded)),
        )
        if selection_key in attempted_sets:
            break
        attempted_sets.add(selection_key)

        attempt_result = _attempt_group(
            state=state,
            config=config,
            root=root,
            selected=selected,
            previous_result=last_result,
        )
        last_result = attempt_result

        if attempt_result.success:
            return _mark_group_success(
                state=state,
                root=root,
                selected=selected,
                attempt_result=attempt_result,
            )

        if attempt_result.status == "password_error":
            root.last_bucket = "password_error"
            root.last_error_kind = attempt_result.status
            root.last_error_message = attempt_result.message
            state.password_failed_candidates[root.source_path] = root
            state.root_candidates.pop(root.source_path, None)
            return ExtractionGroupResult(
                root_path=root.source_path,
                member_paths=[root.source_path] + [item.evidence.source_path for item in selected],
                errors=[attempt_result.message],
                status="password_error",
            )

        if attempt_result.status == "missing_volume":
            if not bootstrapped:
                bootstrapped = True
                bootstrap, bootstrap_policy = pick_bootstrap_candidates(
                    unresolved_count=len(all_candidates),
                    root_count=max(1, len(state.root_candidates)),
                    candidates=all_candidates,
                    missing_volumes=attempt_result.missing_volumes,
                    scoring_config=scoring_config,
                )
                if bootstrap:
                    _log_bootstrap_selection(
                        state=state,
                        root=root,
                        selected=bootstrap,
                        policy=bootstrap_policy,
                        missing_volumes=attempt_result.missing_volumes,
                    )
                    selected.extend(bootstrap)
                    continue

            next_candidate = pick_next_candidate(
                root=root,
                candidates=all_candidates,
                selected=selected,
                excluded=excluded,
                missing_volumes=attempt_result.missing_volumes,
                scoring_config=scoring_config,
            )
            if next_candidate is None:
                break
            _log_next_candidate(
                state=state,
                root=root,
                candidate=next_candidate,
                missing_volumes=attempt_result.missing_volumes,
                reason="missing_volume",
            )
            selected.append(next_candidate)
            continue

        if attempt_result.status == "not_archive":
            if selected:
                removed = min(selected, key=lambda item: item.score)
                selected.remove(removed)
                excluded.add(removed.evidence.source_path)
                state.log_debug(
                    f"[multipart] exclude mismatched member "
                    f"{removed.evidence.source_path} total={removed.score:.3f}",
                )
                _log_score_detail(
                    state,
                    prefix="[multipart] excluded score",
                    candidate=removed,
                )
                continue

            next_candidate = pick_next_candidate(
                root=root,
                candidates=all_candidates,
                selected=selected,
                excluded=excluded,
                missing_volumes=attempt_result.missing_volumes,
                scoring_config=scoring_config,
            )
            if next_candidate is None:
                break
            _log_next_candidate(
                state=state,
                root=root,
                candidate=next_candidate,
                missing_volumes=attempt_result.missing_volumes,
                reason="not_archive",
            )
            selected.append(next_candidate)
            continue

        break

    error_message = (
        last_result.message
        if last_result is not None
        else f"Unable to solve multipart archive: {root.source_path}"
    )
    return ExtractionGroupResult(
        root_path=root.source_path,
        member_paths=[root.source_path] + [item.evidence.source_path for item in selected],
        errors=[error_message],
        status="failed",
    )


def _attempt_group(
    *,
    state: PipelineState,
    config: EmbeddedExtractionConfig,
    root: FileEvidence,
    selected: list[CandidateScore],
    previous_result: ArchiveAttemptResult | None,
) -> ArchiveAttemptResult:
    """把当前主卷和候选卷物化成一组临时文件，然后交给 7-Zip 验证。"""

    group_dir = os.path.join(
        state.working_dir,
        "multipart",
        f"{uuid4().hex[:12]}_{root.family_stem or 'group'}",
    )
    input_dir = os.path.join(group_dir, "input")
    output_dir = os.path.join(group_dir, "output")
    os.makedirs(input_dir, exist_ok=True)

    container = resolve_container(root, selected)
    name_mapping = build_name_mapping(
        root=root,
        selected=selected,
        container=container,
        missing_volumes=(
            previous_result.missing_volumes
            if previous_result is not None
            else list(root.last_missing_volume_names)
        ),
    )
    materialized_root = ""
    try:
        for source_path, target_name in name_mapping.items():
            target_path = os.path.join(input_dir, target_name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)
            if source_path == root.source_path:
                materialized_root = target_path

        state.log_debug(
            "[multipart] try members: "
            + ", ".join(
                f"{os.path.basename(source)}=>{name_mapping[source]}"
                for source in name_mapping
            )
        )
        attempt = extract_archive(
            materialized_root,
            output_dir,
            passwords=config.passwords,
            seven_zip_path=config.seven_zip_path,
        )
        attempt.archive_path = root.source_path
        _log_attempt_result(
            state=state,
            root=root,
            selected=selected,
            attempt=attempt,
            name_mapping=name_mapping,
        )
        if attempt.success:
            final_output_dir = unique_path(
                os.path.join(
                    state.working_dir,
                    "extracted",
                    f"{uuid4().hex[:12]}_{root.family_stem or 'group'}",
                )
            )
            os.makedirs(os.path.dirname(final_output_dir), exist_ok=True)
            shutil.copytree(output_dir, final_output_dir)
            attempt.output_dir = final_output_dir
        shutil.rmtree(group_dir, ignore_errors=True)
        return attempt
    except Exception as exc:
        shutil.rmtree(group_dir, ignore_errors=True)
        return ArchiveAttemptResult(
            status="unknown_error",
            archive_path=root.source_path,
            output_dir=output_dir,
            message=str(exc),
        )


def _mark_group_success(
    *,
    state: PipelineState,
    root: FileEvidence,
    selected: list[CandidateScore],
    attempt_result: ArchiveAttemptResult,
) -> ExtractionGroupResult:
    """把成功组卷产生的结果接回主流程。"""

    member_paths = [root.source_path] + [item.evidence.source_path for item in selected]
    state.extraction_count += 1
    for path in member_paths:
        state.successful_archive_paths.add(path)
        state.source_paths.add(path)
        state.root_candidates.pop(path, None)
        state.unresolved_candidates.pop(path, None)
        state.password_failed_candidates.pop(path, None)

    state.register_extracted_root(
        attempt_result.output_dir,
        parent_path=root.source_path,
    )
    state.log_debug(f"[multipart] success root {root.source_path}")

    return ExtractionGroupResult(
        root_path=root.source_path,
        member_paths=member_paths,
        extracted_files=[attempt_result.output_dir],
        status="success",
    )


def _log_root_priority_table(
    state: PipelineState,
    root_scores: list[RootPriorityScore],
) -> None:
    """记录所有主卷候选的优先级排序。"""

    if not root_scores:
        return
    state.log_debug("[multipart] root priority ranking:")
    for index, item in enumerate(root_scores, start=1):
        state.log_debug(
            f"[multipart] root rank#{index} path={item.evidence.source_path} "
            f"total={item.score:.3f}"
        )
        for component in item.components:
            state.log_debug(_format_component("[multipart]   root score", component))


def _log_root_priority_detail(
    state: PipelineState,
    root_score: RootPriorityScore,
) -> None:
    """记录当前主卷候选的优先级明细。"""

    state.log_debug(
        f"[multipart] root priority detail path={root_score.evidence.source_path} "
        f"total={root_score.score:.3f}"
    )
    for component in root_score.components:
        state.log_debug(_format_component("[multipart]   root priority", component))


def _log_candidate_ranking(
    state: PipelineState,
    root: FileEvidence,
    candidates: list[CandidateScore],
) -> None:
    """记录当前主卷候选对应的候补排行。"""

    state.log_debug(
        f"[multipart] candidate ranking root={root.source_path} count={len(candidates)}"
    )
    for index, candidate in enumerate(candidates, start=1):
        state.log_debug(
            f"[multipart] candidate rank#{index} path={candidate.evidence.source_path} "
            f"base={candidate.base_score:.3f} bonus={candidate.bonus_score:.3f} "
            f"total={candidate.score:.3f}"
        )
        _log_score_detail(
            state,
            prefix="[multipart]   candidate score",
            candidate=candidate,
        )


def _log_bootstrap_selection(
    *,
    state: PipelineState,
    root: FileEvidence,
    selected: list[CandidateScore],
    policy: BootstrapPolicy | None,
    missing_volumes: list[str],
) -> None:
    """记录第一次缺卷反馈后的候选卷批量选择结果。"""

    state.log_debug(
        f"[multipart] bootstrap root={root.source_path} "
        f"missing={missing_volumes} selected={len(selected)}"
    )
    if policy is not None:
        state.log_debug(
            f"[multipart] bootstrap policy mean={policy.mean_score:.3f} "
            f"leader={policy.leader_score:.3f} min_score={policy.min_score:.3f} "
            f"max_gap={policy.max_score_gap:.3f} cap={policy.candidate_cap} "
            f"unresolved={policy.unresolved_count} roots={policy.root_count}"
        )
    for candidate in selected:
        state.log_debug(
            f"[multipart] bootstrap pick path={candidate.evidence.source_path} "
            f"base={candidate.base_score:.3f} bonus={candidate.bonus_score:.3f} "
            f"total={candidate.score:.3f}"
        )
        _log_score_detail(
            state,
            prefix="[multipart]   bootstrap score",
            candidate=candidate,
        )


def _log_same_directory_preflight(
    *,
    state: PipelineState,
    root: FileEvidence,
    selected: list[CandidateScore],
) -> None:
    """Log the same-directory preflight candidates selected before bootstrap."""

    state.log_debug(
        f"[multipart] same-dir preflight root={root.source_path} "
        f"selected={len(selected)}"
    )
    for candidate in selected:
        slot = _infer_preflight_volume_slot(root, candidate.evidence)
        state.log_debug(
            f"[multipart] same-dir preflight pick path={candidate.evidence.source_path} "
            f"slot={slot} total={candidate.score:.3f}"
        )
        _log_score_detail(
            state,
            prefix="[multipart]   same-dir score",
            candidate=candidate,
        )


def _log_next_candidate(
    *,
    state: PipelineState,
    root: FileEvidence,
    candidate: CandidateScore,
    missing_volumes: list[str],
    reason: str,
) -> None:
    """记录当前主卷任务挑选出的下一个候补。"""

    state.log_debug(
        f"[multipart] select next root={root.source_path} reason={reason} "
        f"path={candidate.evidence.source_path} missing={missing_volumes} "
        f"base={candidate.base_score:.3f} bonus={candidate.bonus_score:.3f} "
        f"total={candidate.score:.3f}"
    )
    _log_score_detail(
        state,
        prefix="[multipart]   selected score",
        candidate=candidate,
    )


def _log_score_detail(
    state: PipelineState,
    *,
    prefix: str,
    candidate: CandidateScore,
) -> None:
    """记录一个候补的完整评分明细。"""

    for component in candidate.base_components:
        state.log_debug(_format_component(f"{prefix} base", component))
    for component in candidate.bonus_components:
        state.log_debug(_format_component(f"{prefix} bonus", component))


def _log_attempt_result(
    *,
    state: PipelineState,
    root: FileEvidence,
    selected: list[CandidateScore],
    attempt: ArchiveAttemptResult,
    name_mapping: dict[str, str],
) -> None:
    """记录一次组卷尝试的结果。"""

    members = [root.source_path] + [item.evidence.source_path for item in selected]
    state.log_debug(
        f"[multipart] try result root={root.source_path} status={attempt.status} "
        f"members={len(members)} archive_type={attempt.archive_type or ''} "
        f"password={'yes' if attempt.used_password else 'no'}",
    )
    state.log_debug(
        "[multipart] try result names: "
        + ", ".join(
            f"{os.path.basename(source)}=>{target}"
            for source, target in name_mapping.items()
        )
    )
    if attempt.missing_volumes:
        state.log_debug(f"[multipart] try result missing={attempt.missing_volumes}")
    if attempt.message:
        if attempt.status == "missing_volume":
            state.log_debug(f"[multipart] try result message={attempt.message}")
        else:
            state.log_debug(f"[multipart] try result message={attempt.message}")


def _format_component(prefix: str, component: ScoreComponent) -> str:
    """格式化单个评分项，便于日志稳定输出。"""

    return (
        f"{prefix} name={component.name} "
        f"weight={component.weight:.3f} raw={component.raw_value:.3f} "
        f"contribution={component.contribution:.3f} detail={component.detail}"
    )


def _should_skip_root_only_attempt(root: FileEvidence) -> bool:
    """Return whether the multipart stage can skip the already-known root-only retry."""

    return root.last_error_kind == "missing_volume"


def _pick_same_directory_preflight_candidates(
    *,
    state: PipelineState,
    root: FileEvidence,
    candidates: list[CandidateScore],
) -> list[CandidateScore]:
    """Select same-directory unresolved candidates for a quick pre-bootstrap attempt."""

    if root.last_error_kind != "missing_volume":
        return []

    root_dir = os.path.dirname(root.source_path)
    root_slot = _infer_root_volume_slot(root)
    eligible: list[tuple[int, CandidateScore]] = []

    for candidate in candidates:
        evidence = candidate.evidence
        if evidence.source_path not in state.unresolved_candidates:
            continue
        if os.path.dirname(evidence.source_path) != root_dir:
            continue
        if not _matches_preflight_family(root, evidence):
            continue
        slot = _infer_preflight_volume_slot(root, evidence)
        if slot is None or slot <= root_slot:
            continue
        eligible.append((slot, candidate))

    if not eligible:
        return []

    eligible.sort(key=lambda item: (item[0], -item[1].score, item[1].evidence.source_path))
    selected: list[CandidateScore] = []
    expected_slot = root_slot + 1
    seen_slots: set[int] = set()

    for slot, candidate in eligible:
        if slot in seen_slots:
            continue
        if slot != expected_slot:
            break
        selected.append(candidate)
        seen_slots.add(slot)
        expected_slot += 1

    return selected


def _matches_preflight_family(root: FileEvidence, candidate: FileEvidence) -> bool:
    """Return whether a candidate matches the requested fast-try family constraints."""

    return bool(root.family_tokens) and root.family_tokens == candidate.family_tokens


def _infer_root_volume_slot(root: FileEvidence) -> int:
    """Infer the logical root slot used by the same-directory preflight."""

    if root.filename_volume_index is not None:
        return root.filename_volume_index
    return _rightmost_filename_index(root) or 1


def _infer_preflight_volume_slot(root: FileEvidence, candidate: FileEvidence) -> int | None:
    """Infer a logical volume slot for the same-directory preflight candidates."""

    if candidate.filename_volume_index is not None:
        return candidate.filename_volume_index

    if root.family_tokens != candidate.family_tokens:
        return None

    return _rightmost_filename_index(candidate)


def _rightmost_filename_index(evidence: FileEvidence) -> int | None:
    """Return the rightmost numeric token from the full filename token stream."""

    for token in reversed(evidence.filename_tokens):
        if token.isdigit():
            return int(token)
    return None
