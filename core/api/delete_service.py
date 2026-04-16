from __future__ import annotations

"""Cleanup service helpers."""

import os
from collections.abc import Sequence

from ..delete_ops import safe_remove
from ..workspace import dedupe_paths
from .models import DeleteOptions, DeleteRequest, DeleteResult, ExtractTaskResult


def build_delete_request(
    source_paths: Sequence[str] | None = None,
    *,
    working_dirs: Sequence[str] | None = None,
    source_cleanup_root: str = "",
) -> DeleteRequest:
    """Normalize paths into a cleanup request."""

    return DeleteRequest(
        source_paths=dedupe_paths(source_paths or []),
        working_dirs=dedupe_paths(working_dirs or []),
        source_cleanup_root=os.path.abspath(source_cleanup_root) if source_cleanup_root else "",
    )


def normalize_delete_request(
    target: DeleteRequest | ExtractTaskResult | str | Sequence[str],
) -> DeleteRequest:
    """Accept several input shapes and convert them into a DeleteRequest."""

    if isinstance(target, DeleteRequest):
        return build_delete_request(
            target.source_paths,
            working_dirs=target.working_dirs,
            source_cleanup_root=target.source_cleanup_root,
        )
    if isinstance(target, ExtractTaskResult):
        return normalize_delete_request(target.delete_request)
    if isinstance(target, str):
        return build_delete_request([target])
    if isinstance(target, Sequence):
        return build_delete_request([str(item) for item in target])
    raise TypeError("target must be DeleteRequest, ExtractTaskResult, path, or path sequence")


def delete_artifacts(
    target: DeleteRequest | ExtractTaskResult | str | Sequence[str],
    options: DeleteOptions,
) -> DeleteResult:
    """Execute one cleanup request."""

    delete_request = normalize_delete_request(target)
    removed_paths: list[str] = []
    skipped_paths: list[str] = []
    failed_paths: list[str] = []
    messages: list[str] = []
    source_path_set = {os.path.abspath(source_path) for source_path in delete_request.source_paths}

    for path in dedupe_paths(delete_request.source_paths + delete_request.working_dirs):
        if not os.path.exists(path):
            skipped_paths.append(path)
            continue

        is_source_path = os.path.abspath(path) in source_path_set
        success = safe_remove(
            path,
            use_recycle_bin=options.use_recycle_bin,
            error_callback=messages.append,
        )
        if success:
            removed_paths.append(path)
            if is_source_path:
                removed_paths.extend(
                    _cleanup_empty_parent_directories(
                        path,
                        stop_at_root=delete_request.source_cleanup_root,
                        error_callback=messages.append,
                    )
                )
            continue

        failed_paths.append(path)
        if not messages:
            messages.append(f"删除失败：{path}")

    return DeleteResult(
        removed_paths=removed_paths,
        moved_paths=[],
        skipped_paths=skipped_paths,
        failed_paths=failed_paths,
        messages=messages,
    )


def merge_delete_requests(*requests: DeleteRequest) -> DeleteRequest:
    """Merge several cleanup requests into one."""

    source_paths: list[str] = []
    working_dirs: list[str] = []
    source_cleanup_root = ""

    for request in requests:
        source_paths.extend(request.source_paths)
        working_dirs.extend(request.working_dirs)
        if not source_cleanup_root and request.source_cleanup_root:
            source_cleanup_root = request.source_cleanup_root

    return build_delete_request(
        source_paths,
        working_dirs=working_dirs,
        source_cleanup_root=source_cleanup_root,
    )


def _cleanup_empty_parent_directories(
    path: str,
    *,
    stop_at_root: str,
    error_callback=None,
) -> list[str]:
    """Delete empty parent directories above a removed source file."""

    removed_paths: list[str] = []
    stop_root = os.path.abspath(stop_at_root) if stop_at_root else ""
    current_dir = os.path.dirname(os.path.abspath(path))

    while current_dir:
        if stop_root:
            try:
                if os.path.commonpath([current_dir, stop_root]) != stop_root:
                    break
            except ValueError:
                break

        try:
            if stop_root and os.path.samefile(current_dir, stop_root):
                if os.listdir(current_dir):
                    break
                os.rmdir(current_dir)
                removed_paths.append(current_dir)
                break
        except (OSError, FileNotFoundError):
            pass

        try:
            if os.listdir(current_dir):
                break
            os.rmdir(current_dir)
            removed_paths.append(current_dir)
        except OSError as exc:
            if error_callback is not None:
                error_callback(f"删除空目录失败：{current_dir}。原因：{exc}")
            break

        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            break
        current_dir = parent_dir

    return removed_paths
