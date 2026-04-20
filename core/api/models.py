from __future__ import annotations

"""Public data models used by the task API."""

from dataclasses import dataclass, field
from typing import Callable

from ..extraction_types import (
    DeepProbeDecision,
    EmbeddedExtractionResult,
    ExtractedRootDecisionRequest,
    ProcessLogEntry,
)


@dataclass(slots=True)
class ExtractOptions:
    """Public extraction options."""

    passwords: list[str] = field(default_factory=list)
    detect_polyglot_archives: bool = True
    detect_disguised_archives: bool = True
    delete_source_archives: bool = False
    delete_working_dir: bool = False
    promote_output_contents_to_workspace: bool = True
    use_recycle_bin: bool = True
    save_passwords: bool = False
    max_depth: int = 10
    seven_zip_path: str | None = None
    output_dir_name: str = "unzipped"
    working_dir_name: str = ".complex_unzip_work"
    workspace_suffix_length: int = 6
    prompt_on_large_extracted_root: bool = False
    extracted_root_fast_track_file_threshold: int = 64
    extracted_root_fast_track_dir_threshold: int = 12
    extracted_root_threshold_mode: str = "or"
    extracted_root_preview_limit: int = 12
    live_process_log_handler: Callable[[ProcessLogEntry], None] | None = None
    extracted_root_decision_handler: Callable[
        [ExtractedRootDecisionRequest], DeepProbeDecision
    ] | None = None


@dataclass(slots=True)
class DeleteOptions:
    """Options for the cleanup stage."""

    use_recycle_bin: bool = True


@dataclass(slots=True)
class DeleteRequest:
    """Paths scheduled for cleanup after extraction."""

    source_paths: list[str] = field(default_factory=list)
    working_dirs: list[str] = field(default_factory=list)
    source_cleanup_root: str = ""


@dataclass(slots=True)
class DeleteResult:
    """Cleanup summary."""

    removed_paths: list[str] = field(default_factory=list)
    moved_paths: list[str] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)
    failed_paths: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether cleanup finished without failed paths."""

        return not self.failed_paths


@dataclass(slots=True)
class ExtractTaskPlan:
    """Resolved filesystem plan for one task."""

    input_path: str
    task_kind: str
    workspace_dir: str
    output_dir: str
    working_dir: str


@dataclass(slots=True)
class ExtractTaskResult:
    """Result of one extraction task."""

    plan: ExtractTaskPlan
    extraction: EmbeddedExtractionResult
    cleanup: DeleteResult = field(default_factory=DeleteResult)
    delete_request: DeleteRequest = field(default_factory=DeleteRequest)

    @property
    def success(self) -> bool:
        """Whether extraction and cleanup both succeeded."""

        return self.extraction.success and self.cleanup.success


@dataclass(slots=True)
class ExtractBatchResult:
    """Result of a batch extraction run."""

    tasks: list[ExtractTaskResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether every task in the batch succeeded."""

        return bool(self.tasks) and all(task.success for task in self.tasks)
