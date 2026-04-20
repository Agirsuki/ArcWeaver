from __future__ import annotations

"""Desktop settings persistence and conversion helpers."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import tkinter as tk

from core.api.models import ExtractOptions


@dataclass(slots=True)
class UiSettings:
    """Persistent settings used by the desktop interface."""

    mode: str = "single"
    single_path: str = ""
    multi_root: str = ""
    keep_source: bool = True
    detect_polyglot: bool = True
    cleanup: bool = False
    promote_output: bool = True
    recycle: bool = True
    prompt_large_extracted_root: bool = True
    large_root_file_threshold: int = 64
    large_root_dir_threshold: int = 12
    large_root_threshold_mode: str = "and"
    large_root_preview_limit: int = 12
    passwords: list[str] = field(default_factory=list)


def default_ui_settings() -> UiSettings:
    """Return the default desktop settings."""

    return UiSettings()


def load_ui_settings(settings_path: Path) -> UiSettings:
    """Load desktop settings from disk and fall back to defaults on failure."""

    defaults = default_ui_settings()
    if not settings_path.exists():
        return defaults
    try:
        raw_data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    return UiSettings(
        mode=str(raw_data.get("mode", defaults.mode)),
        single_path=str(raw_data.get("single_path", defaults.single_path)),
        multi_root=str(raw_data.get("multi_root", defaults.multi_root)),
        keep_source=bool(raw_data.get("keep_source", defaults.keep_source)),
        detect_polyglot=bool(raw_data.get("detect_polyglot", defaults.detect_polyglot)),
        cleanup=bool(raw_data.get("cleanup", defaults.cleanup)),
        promote_output=bool(raw_data.get("promote_output", defaults.promote_output)),
        recycle=bool(raw_data.get("recycle", defaults.recycle)),
        prompt_large_extracted_root=bool(
            raw_data.get(
                "prompt_large_extracted_root",
                defaults.prompt_large_extracted_root,
            )
        ),
        large_root_file_threshold=max(
            1,
            int(
                raw_data.get(
                    "large_root_file_threshold",
                    defaults.large_root_file_threshold,
                )
            ),
        ),
        large_root_dir_threshold=max(
            1,
            int(
                raw_data.get(
                    "large_root_dir_threshold",
                    defaults.large_root_dir_threshold,
                )
            ),
        ),
        large_root_threshold_mode=(
            "and"
            if str(
                raw_data.get(
                    "large_root_threshold_mode",
                    defaults.large_root_threshold_mode,
                )
            ).strip().lower() == "and"
            else "or"
        ),
        large_root_preview_limit=max(
            0,
            int(
                raw_data.get(
                    "large_root_preview_limit",
                    defaults.large_root_preview_limit,
                )
            ),
        ),
        passwords=_normalize_passwords(raw_data.get("passwords", defaults.passwords)),
    )


def save_ui_settings(settings_path: Path, settings: UiSettings) -> None:
    """Persist the current desktop settings as UTF-8 JSON."""

    persisted = {
        "mode": settings.mode,
        "single_path": settings.single_path,
        "multi_root": settings.multi_root,
        "keep_source": settings.keep_source,
        "detect_polyglot": settings.detect_polyglot,
        "cleanup": settings.cleanup,
        "promote_output": settings.promote_output,
        "recycle": settings.recycle,
        "prompt_large_extracted_root": settings.prompt_large_extracted_root,
        "large_root_file_threshold": settings.large_root_file_threshold,
        "large_root_dir_threshold": settings.large_root_dir_threshold,
        "large_root_threshold_mode": settings.large_root_threshold_mode,
        "large_root_preview_limit": settings.large_root_preview_limit,
        "passwords": list(settings.passwords),
    }
    settings_path.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_passwords_from_text(raw_text: str) -> list[str]:
    """Split the password editor content into a normalized password list."""

    return _normalize_passwords(raw_text.splitlines())


def sync_bool_state(var: tk.BooleanVar, text_var: tk.StringVar) -> None:
    """Keep the small on/off state label in sync with a checkbutton value."""

    def _update(*_args) -> None:
        text_var.set("已开启" if var.get() else "已关闭")

    var.trace_add("write", _update)
    _update()


def build_extract_options_from_settings(settings: UiSettings) -> ExtractOptions:
    """Convert desktop settings into the public extraction options object."""

    return ExtractOptions(
        passwords=list(settings.passwords),
        detect_polyglot_archives=settings.detect_polyglot,
        detect_disguised_archives=True,
        delete_source_archives=not settings.keep_source,
        delete_working_dir=settings.cleanup,
        promote_output_contents_to_workspace=settings.promote_output,
        use_recycle_bin=settings.recycle,
        save_passwords=False,
        max_depth=10,
        seven_zip_path=None,
        output_dir_name="unzipped",
        working_dir_name=".complex_unzip_work",
        workspace_suffix_length=6,
        prompt_on_large_extracted_root=settings.prompt_large_extracted_root,
        extracted_root_fast_track_file_threshold=settings.large_root_file_threshold,
        extracted_root_fast_track_dir_threshold=settings.large_root_dir_threshold,
        extracted_root_threshold_mode=settings.large_root_threshold_mode,
        extracted_root_preview_limit=settings.large_root_preview_limit,
    )


def _normalize_passwords(raw_passwords) -> list[str]:
    """Trim, deduplicate, and preserve password order."""

    if isinstance(raw_passwords, str):
        raw_values = raw_passwords.splitlines()
    elif isinstance(raw_passwords, list):
        raw_values = raw_passwords
    else:
        raw_values = []

    passwords: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value and value not in passwords:
            passwords.append(value)
    return passwords
