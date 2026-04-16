from __future__ import annotations

"""Small path utilities shared by workflow and publishing code."""

import os


def unique_path(path: str) -> str:
    """Return a collision-free variant of the given path."""

    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    counter = 2
    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def task_roots_from_inputs(paths: list[str]) -> list[str]:
    """Map task inputs to the root directories the workflow should scan."""

    roots: list[str] = []
    for path in paths:
        absolute_path = os.path.abspath(path)
        if os.path.isdir(absolute_path):
            roots.append(absolute_path)
        else:
            roots.append(os.path.dirname(absolute_path) or absolute_path)
    return list(dict.fromkeys(roots))
