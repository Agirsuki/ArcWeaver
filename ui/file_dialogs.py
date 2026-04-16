from __future__ import annotations

"""Thin wrappers around Tk file dialogs."""

from pathlib import Path
from tkinter import Misc, filedialog


def pick_directory(parent: Misc | None, initial_dir: str = "") -> str:
    """Open a single-directory picker and return an absolute path."""

    selected = filedialog.askdirectory(
        parent=parent,
        initialdir=_normalize_initial_dir(initial_dir),
    )
    if not selected:
        return ""
    return str(Path(selected).resolve())


def _normalize_initial_dir(initial_dir: str) -> str:
    """Convert a file or directory hint into a valid Tk initial directory."""

    if not initial_dir:
        return ""

    candidate = Path(initial_dir).expanduser()
    if candidate.is_file():
        candidate = candidate.parent
    if candidate.exists():
        return str(candidate.resolve())
    return ""
