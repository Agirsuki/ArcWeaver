from __future__ import annotations

"""Task workspace planning helpers."""

from dataclasses import dataclass
import os
import random
from collections.abc import Iterable


_RANDOM_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(slots=True)
class TaskPlan:
    """Resolved workspace layout for a single input path."""

    input_path: str
    task_kind: str
    workspace_dir: str
    output_dir: str
    working_dir: str


def build_task_plan(input_path: str, options) -> TaskPlan:
    """Build the directory plan used by the public task API."""

    absolute_input = os.path.abspath(input_path)
    if os.path.isdir(absolute_input):
        workspace_dir = absolute_input
        return TaskPlan(
            input_path=absolute_input,
            task_kind="directory",
            workspace_dir=workspace_dir,
            output_dir=os.path.join(workspace_dir, options.output_dir_name),
            working_dir=os.path.join(workspace_dir, options.working_dir_name),
        )

    workspace_dir = build_file_workspace_dir(
        absolute_input,
        suffix_length=getattr(options, "workspace_suffix_length", 6),
    )
    return TaskPlan(
        input_path=absolute_input,
        task_kind="file",
        workspace_dir=workspace_dir,
        output_dir=os.path.join(workspace_dir, options.output_dir_name),
        working_dir=os.path.join(workspace_dir, options.working_dir_name),
    )


def build_file_workspace_dir(file_path: str, *, suffix_length: int = 6) -> str:
    """Pick a workspace directory for a single-file task."""

    absolute_file = os.path.abspath(file_path)
    parent_dir = os.path.dirname(absolute_file)
    raw_basename = os.path.splitext(os.path.basename(absolute_file))[0] or "archive"
    safe_basename = sanitize_workspace_basename(raw_basename)
    suffix_length = max(4, int(suffix_length))

    direct_candidate = os.path.join(parent_dir, safe_basename)
    if not os.path.exists(direct_candidate):
        return direct_candidate

    while True:
        short_code = "".join(random.choice(_RANDOM_ALPHABET) for _ in range(suffix_length))
        candidate = os.path.join(parent_dir, f"{safe_basename}_{short_code}")
        if not os.path.exists(candidate):
            return candidate


def sanitize_workspace_basename(value: str) -> str:
    """Remove filesystem-hostile characters from a workspace directory name."""

    sanitized = "".join(
        "_" if char in '<>:"/\\|?*' or ord(char) < 32 else char
        for char in value
    ).strip(" .")
    return sanitized or "archive"


def dedupe_paths(paths: Iterable[str]) -> list[str]:
    """Deduplicate paths while preserving the first-seen absolute path order."""

    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        absolute_path = os.path.abspath(path)
        if absolute_path in seen:
            continue
        seen.add(absolute_path)
        ordered.append(absolute_path)
    return ordered
