from __future__ import annotations

"""Public task service entry points."""

from collections.abc import Sequence
from typing import Any, Mapping

from ..extraction_types import EmbeddedExtractionConfig
from ..workflow.runner import process_downloads
from ..workspace import build_task_plan, dedupe_paths
from .models import ExtractBatchResult, ExtractOptions, ExtractTaskPlan, ExtractTaskResult
from .options import normalize_extract_options
from .task_cleanup import finalize_task_cleanup


def extract_task(
    path: str,
    options: ExtractOptions | Mapping[str, Any] | None = None,
) -> ExtractTaskResult:
    """Run one extraction task and return its result."""

    return extract_tasks([path], options).tasks[0]


def extract_tasks(
    paths: str | Sequence[str],
    options: ExtractOptions | Mapping[str, Any] | None = None,
) -> ExtractBatchResult:
    """Run a batch of extraction tasks in order."""

    normalized_options = normalize_extract_options(options)
    normalized_paths = _normalize_input_paths(paths)
    task_results: list[ExtractTaskResult] = []

    for path in normalized_paths:
        plan = build_task_plan(path, normalized_options)
        extraction_result = process_downloads(
            [plan.input_path],
            _build_embedded_config(plan, normalized_options),
        )
        cleanup_result, delete_request = finalize_task_cleanup(
            plan=plan,
            extraction_result=extraction_result,
            options=normalized_options,
        )
        task_results.append(
            ExtractTaskResult(
                plan=ExtractTaskPlan(
                    input_path=plan.input_path,
                    task_kind=plan.task_kind,
                    workspace_dir=plan.workspace_dir,
                    output_dir=plan.output_dir,
                    working_dir=plan.working_dir,
                ),
                extraction=extraction_result,
                cleanup=cleanup_result,
                delete_request=delete_request,
            )
        )

    return ExtractBatchResult(tasks=task_results)


def _normalize_input_paths(paths: str | Sequence[str]) -> list[str]:
    """Normalize input paths into a deduplicated absolute-path list."""

    if isinstance(paths, str):
        normalized = [paths]
    else:
        normalized = [str(path) for path in paths]
    if not normalized:
        raise ValueError("paths must not be empty")
    return dedupe_paths(normalized)


def _build_embedded_config(
    plan,
    options: ExtractOptions,
) -> EmbeddedExtractionConfig:
    """Convert public options into the workflow configuration."""

    return EmbeddedExtractionConfig(
        output_dir=plan.output_dir,
        working_dir=plan.working_dir,
        passwords=list(dict.fromkeys(options.passwords)),
        max_depth=options.max_depth,
        detect_polyglot_archives=options.detect_polyglot_archives,
        detect_disguised_archives=options.detect_disguised_archives,
        promote_output_contents_to_workspace=options.promote_output_contents_to_workspace,
        use_recycle_bin=options.use_recycle_bin,
        save_passwords=options.save_passwords,
        seven_zip_path=options.seven_zip_path,
        extracted_root_fast_track_file_threshold=options.extracted_root_fast_track_file_threshold,
        extracted_root_fast_track_dir_threshold=options.extracted_root_fast_track_dir_threshold,
        extracted_root_preview_limit=options.extracted_root_preview_limit,
        prompt_on_large_extracted_root=options.prompt_on_large_extracted_root,
        live_process_log_handler=options.live_process_log_handler,
        extracted_root_threshold_mode=options.extracted_root_threshold_mode,
        extracted_root_decision_handler=options.extracted_root_decision_handler,
    )
