from __future__ import annotations

"""Workflow runner for recursive extraction."""

import os
import shutil

from ..extraction_config import normalize_embedded_config
from ..extraction_types import EmbeddedExtractionConfig, EmbeddedExtractionResult
from ..multipart.solver import solve_pending_multipart
from ..path_ops import task_roots_from_inputs
from .publish import publish_final_outputs
from .recursive_extraction import run_recursive_extraction_pass
from .scanner import iter_scan_files
from .state import PipelineState


def process_downloads(
    paths: list[str],
    config: EmbeddedExtractionConfig | dict | None = None,
) -> EmbeddedExtractionResult:
    """Run the full recursive extraction and multipart recovery workflow."""

    normalized_config = normalize_embedded_config(config)
    task_roots = task_roots_from_inputs(paths)
    output_dir = os.path.abspath(
        normalized_config.output_dir
        or os.path.join(task_roots[0], "unzipped")
    )
    working_dir = os.path.abspath(
        normalized_config.working_dir
        or os.path.join(task_roots[0], ".complex_unzip_work")
    )

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(working_dir, exist_ok=True)
    _prepare_working_environment(working_dir)

    state = PipelineState(
        source_roots=list(task_roots),
        output_dir=output_dir,
        working_dir=working_dir,
        scan_roots=list(task_roots),
        max_depth=normalized_config.max_depth,
    )

    while True:
        files = _collect_round_files(state)
        recursive_result = run_recursive_extraction_pass(
            state,
            config=normalized_config,
            file_paths=files,
        )
        if recursive_result.new_extractions:
            continue

        multipart_successes = solve_pending_multipart(
            state,
            config=normalized_config,
        )
        if multipart_successes:
            continue
        break

    extracted_files, publish_errors = publish_final_outputs(state)
    state.errors.extend(error for error in publish_errors if error not in state.errors)
    status = _resolve_status(state, extracted_files)
    next_action = _resolve_next_action(state, status)

    return EmbeddedExtractionResult(
        output_dir=output_dir,
        working_dir=working_dir,
        status=status,
        next_action=next_action,
        scanned_files=sorted(state.scanned_files),
        extracted_files=extracted_files,
        source_paths=sorted(state.source_paths),
        repaired_files=sorted(
            path
            for path, evidence in state.evidence_by_path.items()
            if evidence.notes
        ),
        root_candidates=sorted(state.root_candidates),
        unresolved_candidates=sorted(state.unresolved_candidates),
        password_failed_candidates=sorted(state.password_failed_candidates),
        file_evidences=list(state.evidence_by_path.values()),
        group_results=state.group_results,
        errors=state.errors,
        process_log=list(state.process_log),
        discovered_passwords=[],
    )


def _prepare_working_environment(working_dir: str) -> None:
    """Clear old working data while preserving plain-text debug files."""

    preserved_suffixes = {".log", ".txt", ".json"}
    for child_name in os.listdir(working_dir):
        child_path = os.path.join(working_dir, child_name)
        if os.path.isfile(child_path) and os.path.splitext(child_name)[1].lower() in preserved_suffixes:
            continue
        if os.path.isdir(child_path):
            shutil.rmtree(child_path, ignore_errors=True)
        else:
            try:
                os.remove(child_path)
            except OSError:
                continue


def _resolve_status(state: PipelineState, extracted_files: list[str]) -> str:
    """Resolve the final task status from output and residual candidates."""

    has_failures = bool(
        state.errors
        or state.root_candidates
        or state.unresolved_candidates
        or state.password_failed_candidates
    )
    if extracted_files and not has_failures:
        return "success"
    if extracted_files:
        return "partial_success"
    return "failed"


def _resolve_next_action(state: PipelineState, status: str) -> str:
    """Resolve the next suggested action for the caller."""

    if status == "success":
        return "complete"
    if state.password_failed_candidates:
        return "provide_passwords"
    if state.root_candidates:
        return "locate_missing_volumes"
    return "inspect_errors"


def _collect_round_files(state: PipelineState) -> list[str]:
    """Collect files that should participate in the current processing round."""

    source_files = iter_scan_files(
        state.source_roots,
        ignored_roots=[state.output_dir, state.working_dir],
    )
    extracted_files = iter_scan_files(
        state.scannable_extracted_roots(),
        ignored_roots=[
            os.path.join(state.working_dir, "multipart"),
            os.path.join(state.working_dir, "probes"),
            os.path.join(state.working_dir, "polyglot"),
            os.path.join(state.working_dir, "forced_extension_probe"),
            os.path.join(state.working_dir, "finalized"),
        ],
    )
    return list(dict.fromkeys(source_files + extracted_files))
