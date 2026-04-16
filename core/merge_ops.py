from __future__ import annotations

"""Merge helpers used when publishing extracted output."""

import filecmp
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class MergeActionResult:
    """Summary of one merge or promotion operation."""

    moved_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    failed_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether the merge completed without failures."""

        return not self.failed_paths and not self.errors


def merge_children_into_directory(
    *,
    source_dir: str,
    destination_dir: str,
    unique_path: Callable[[str], str],
) -> MergeActionResult:
    """Move the direct children of a directory into the destination tree."""

    result = MergeActionResult()
    if not os.path.isdir(source_dir):
        result.failed_paths.append(source_dir)
        result.errors.append("Source directory not found during output promotion")
        return result

    os.makedirs(destination_dir, exist_ok=True)

    for child_name in sorted(os.listdir(source_dir)):
        source_child = os.path.join(source_dir, child_name)
        target_child = os.path.join(destination_dir, child_name)
        if os.path.isdir(source_child):
            nested_result = merge_directory_contents(
                source_dir=source_child,
                destination_dir=target_child,
                unique_path=unique_path,
            )
            result.moved_paths.extend(nested_result.moved_paths)
            result.removed_paths.extend(nested_result.removed_paths)
            result.failed_paths.extend(nested_result.failed_paths)
            result.errors.extend(nested_result.errors)
            continue

        try:
            final_path, reused_existing = merge_file_with_conflict_policy(
                source_path=source_child,
                destination_path=target_child,
                unique_path=unique_path,
            )
        except OSError as exc:
            result.failed_paths.append(source_child)
            result.errors.append(f"Failed to promote output file: {exc}")
            continue

        if reused_existing:
            result.removed_paths.append(source_child)
        result.moved_paths.append(final_path)

    _remove_empty_directory(source_dir, result.removed_paths)
    return result


def merge_directory_contents(
    *,
    source_dir: str,
    destination_dir: str,
    unique_path: Callable[[str], str],
) -> MergeActionResult:
    """Recursively merge one directory tree into another."""

    result = MergeActionResult()
    if not os.path.isdir(source_dir):
        result.failed_paths.append(source_dir)
        result.errors.append("Source directory not found during merge")
        return result

    os.makedirs(destination_dir, exist_ok=True)
    for child_name in sorted(os.listdir(source_dir)):
        source_child = os.path.join(source_dir, child_name)
        target_child = os.path.join(destination_dir, child_name)
        if os.path.isdir(source_child):
            nested_result = merge_directory_contents(
                source_dir=source_child,
                destination_dir=target_child,
                unique_path=unique_path,
            )
            result.moved_paths.extend(nested_result.moved_paths)
            result.removed_paths.extend(nested_result.removed_paths)
            result.failed_paths.extend(nested_result.failed_paths)
            result.errors.extend(nested_result.errors)
            continue

        try:
            final_path, reused_existing = merge_file_with_conflict_policy(
                source_path=source_child,
                destination_path=target_child,
                unique_path=unique_path,
            )
        except OSError as exc:
            result.failed_paths.append(source_child)
            result.errors.append(f"Failed to merge file during output promotion: {exc}")
            continue

        if reused_existing:
            result.removed_paths.append(source_child)
        result.moved_paths.append(final_path)

    _remove_empty_directory(source_dir, result.removed_paths)
    return result


def merge_file_with_conflict_policy(
    *,
    source_path: str,
    destination_path: str,
    unique_path: Callable[[str], str],
) -> tuple[str, bool]:
    """Merge one file, reusing identical targets or creating a unique name."""

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)

    if os.path.exists(destination_path):
        if _files_match_strict(source_path, destination_path):
            _remove_if_exists(source_path)
            return destination_path, True
        destination_path = unique_path(destination_path)

    try:
        shutil.move(source_path, destination_path)
    except (OSError, PermissionError):
        shutil.copy2(source_path, destination_path)
        _remove_if_exists(source_path)
    return destination_path, False


def _files_match_strict(left_path: str, right_path: str) -> bool:
    """Compare file contents in strict mode."""

    try:
        return filecmp.cmp(left_path, right_path, shallow=False)
    except OSError:
        return False


def _remove_if_exists(path: str) -> bool:
    """Best-effort file removal used during merge cleanup."""

    try:
        if os.path.exists(path):
            os.remove(path)
        return not os.path.exists(path)
    except OSError:
        return False


def _remove_empty_directory(path: str, removed_paths: list[str]) -> None:
    """Remove a directory after merge if it became empty."""

    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
            removed_paths.append(path)
    except OSError:
        pass
