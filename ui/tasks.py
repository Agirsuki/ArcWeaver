from __future__ import annotations

"""Task list helpers used by the desktop application."""

from dataclasses import dataclass
import hashlib
import os
import re


_ARCHIVE_SUFFIXES = (
    ".7z",
    ".zip",
    ".rar",
    ".tar",
    ".tar.zst",
    ".tzst",
    ".zst",
    ".gz",
    ".bz2",
    ".xz",
    ".001",
    ".z01",
    ".r00",
)
_ARCHIVE_PATTERN = re.compile(
    r"(\.part\d+\.rar$)|(\.z\d{2}$)|(\.r\d{2}$)|(\.(7z|zip)\.\d+$)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TaskItem:
    """One task row shown in the desktop task list."""

    task_id: str
    path: str
    display_name: str
    kind: str
    archive_count: int
    selected: bool = True


def make_task_items(
    paths: list[str],
    expected_kind: str,
    existing_ids: set[str],
) -> list[TaskItem]:
    """Create deduplicated task rows from a batch of selected paths."""

    new_tasks: list[TaskItem] = []
    for path in paths:
        absolute_path = os.path.abspath(path)
        if expected_kind == "file" and not os.path.isfile(absolute_path):
            continue
        if expected_kind == "dir" and not os.path.isdir(absolute_path):
            continue
        task_id = build_task_id(absolute_path)
        if task_id in existing_ids:
            continue
        new_tasks.append(
            TaskItem(
                task_id=task_id,
                path=absolute_path,
                display_name=build_task_display_name(absolute_path, kind=expected_kind),
                kind="file" if expected_kind == "file" else "dir",
                archive_count=count_archives(absolute_path),
                selected=True,
            )
        )
        existing_ids.add(task_id)
    return new_tasks


def build_task_id(path: str) -> str:
    """Build a stable short identifier from an absolute path."""

    return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]


def build_task_display_name(path: str, *, kind: str) -> str:
    """Return a short name for the task list."""

    base_name = os.path.basename(path.rstrip("\\/"))
    if base_name:
        return base_name
    return "文件任务" if kind == "file" else "目录任务"


def count_archives(path: str) -> int:
    """Count archive-like files under a path for task preview purposes."""

    if os.path.isfile(path):
        return 1 if is_archive_like(path) else 0
    total = 0
    for current_root, _dirs, files in os.walk(path):
        for filename in files:
            if is_archive_like(os.path.join(current_root, filename)):
                total += 1
    return total


def is_archive_like(path: str) -> bool:
    """Best-effort archive-like detector used only for UI statistics."""

    filename = os.path.basename(path).lower()
    return any(filename.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES) or bool(
        _ARCHIVE_PATTERN.search(filename)
    )


def summarize_tasks(tasks: list[TaskItem]) -> str:
    """Build the compact summary text shown above the task table."""

    total = len(tasks)
    return f"?? {total}"
