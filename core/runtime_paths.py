from __future__ import annotations

"""Runtime path helpers for source runs and frozen builds."""

import os
import sys
from pathlib import Path


def get_runtime_root() -> Path:
    """Return the project root or the extracted PyInstaller root."""

    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def get_runtime_resource_path(*relative_parts: str) -> str:
    """Resolve a runtime resource path relative to the runtime root."""

    return str(get_runtime_root().joinpath(*relative_parts))


def get_default_7z_path() -> str:
    """Return the bundled 7-Zip executable path."""

    return get_runtime_resource_path("7z", "7z.exe")


def get_default_cloaked_rules_path() -> str:
    """Return the default cloaked-file rules path."""

    return get_runtime_resource_path("core", "config", "cloaked_file_rules.json")


def get_default_multipart_scoring_path() -> str:
    """Return the default multipart scoring config path."""

    return get_runtime_resource_path("core", "config", "multipart_scoring.json")


def get_build_output_dir() -> str:
    """Return the conventional build output directory under the project root."""

    return os.path.join(str(get_runtime_root()), "dist")
