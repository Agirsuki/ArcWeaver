from __future__ import annotations

"""Final output publishing helpers."""

import os
from typing import Iterable

from ..extraction_types import WorkspacePromotionResult
from ..merge_ops import merge_children_into_directory
from ..path_ops import unique_path
from .state import PipelineState


def publish_final_outputs(state: PipelineState) -> tuple[list[str], list[str]]:
    """Merge final extracted files into the unzipped directory."""

    os.makedirs(state.output_dir, exist_ok=True)
    errors: list[str] = []
    moved_paths: list[str] = []
    excluded_paths = _build_excluded_paths(state)

    for extract_root in list(dict.fromkeys(state.extracted_roots)):
        if not os.path.isdir(extract_root):
            continue
        _prune_excluded_files(extract_root, excluded_paths)
        result = merge_children_into_directory(
            source_dir=extract_root,
            destination_dir=state.output_dir,
            unique_path=unique_path,
        )
        moved_paths.extend(result.moved_paths)
        errors.extend(result.errors)

    finalized_dir = os.path.join(state.working_dir, "finalized")
    if os.path.isdir(finalized_dir):
        result = merge_children_into_directory(
            source_dir=finalized_dir,
            destination_dir=state.output_dir,
            unique_path=unique_path,
        )
        moved_paths.extend(result.moved_paths)
        errors.extend(result.errors)

    return list(dict.fromkeys(moved_paths)), list(dict.fromkeys(errors))


def promote_output_dir_contents(
    workspace_dir: str,
    output_dir_name: str = "unzipped",
) -> WorkspacePromotionResult:
    """Promote the contents of unzipped back into the workspace directory."""

    workspace_abs = os.path.abspath(workspace_dir)
    output_abs = os.path.join(workspace_abs, output_dir_name)

    if not os.path.isdir(workspace_abs):
        return WorkspacePromotionResult(
            success=False,
            workspace_dir=workspace_abs,
            output_dir=output_abs,
            errors=[f"Workspace directory not found: {workspace_abs}"],
        )
    if not os.path.isdir(output_abs):
        return WorkspacePromotionResult(
            success=False,
            workspace_dir=workspace_abs,
            output_dir=output_abs,
            errors=[f"Output directory not found: {output_abs}"],
        )

    result = merge_children_into_directory(
        source_dir=output_abs,
        destination_dir=workspace_abs,
        unique_path=unique_path,
    )
    return WorkspacePromotionResult(
        success=result.success,
        workspace_dir=workspace_abs,
        output_dir=output_abs,
        moved_paths=result.moved_paths,
        removed_paths=result.removed_paths,
        errors=result.errors,
    )


def _build_excluded_paths(state: PipelineState) -> set[str]:
    """Build the set of intermediate or unresolved files that must stay unpublished."""

    excluded = set(state.successful_archive_paths)
    excluded.update(state.root_candidates)
    excluded.update(state.unresolved_candidates)
    excluded.update(state.password_failed_candidates)
    return {os.path.abspath(path) for path in excluded}


def _prune_excluded_files(root: str, excluded_paths: Iterable[str]) -> None:
    """Remove excluded files before publishing merged output."""

    excluded = set(os.path.abspath(path) for path in excluded_paths)
    for current_root, _dirs, files in os.walk(root):
        for filename in files:
            file_path = os.path.abspath(os.path.join(current_root, filename))
            if file_path not in excluded:
                continue
            try:
                os.remove(file_path)
            except OSError:
                continue
