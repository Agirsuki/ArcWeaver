from __future__ import annotations

"""Core dataclasses shared by the extraction workflow."""

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional


TaskStatus = Literal["success", "partial_success", "failed"]
FileKind = Literal["archive", "non_archive", "unknown"]
CandidateBucket = Literal["root", "unresolved", "password_error", "final"]
DeepProbeDecision = Literal["continue", "skip_once", "skip_default"]


@dataclass(slots=True)
class ExtractedRootDecisionRequest:
    """Prompt payload for deciding whether one extracted root should deep-probe."""

    root_path: str
    parent_archive_path: str
    depth: int
    file_count: int
    dir_count: int
    sample_entries: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EmbeddedExtractionConfig:
    """Settings consumed by the internal extraction workflow."""

    output_dir: Optional[str] = None
    working_dir: Optional[str] = None
    passwords: list[str] = field(default_factory=list)
    seven_zip_path: Optional[str] = None
    max_depth: int = 10
    detect_polyglot_archives: bool = True
    detect_disguised_archives: bool = True
    promote_output_contents_to_workspace: bool = True
    use_recycle_bin: bool = True
    save_passwords: bool = False
    force_probe_extensions: tuple[str, ...] = ("zip", "7z", "rar")
    multipart_bootstrap_count: int = 3
    multipart_max_candidates: int = 32
    extracted_root_fast_track_file_threshold: int = 64
    extracted_root_fast_track_dir_threshold: int = 12
    extracted_root_threshold_mode: Literal["or", "and"] = "or"
    extracted_root_preview_limit: int = 12
    prompt_on_large_extracted_root: bool = False
    live_process_log_handler: Optional[Callable[[ProcessLogEntry], None]] = None
    extracted_root_decision_handler: Optional[
        Callable[[ExtractedRootDecisionRequest], DeepProbeDecision]
    ] = None


@dataclass(slots=True)
class FileEvidence:
    """Observed facts collected for one scanned file."""

    source_path: str
    display_name: str
    size_bytes: int
    family_stem: str
    family_core: str
    normalized_family: str
    family_tokens: tuple[str, ...]
    digit_tokens: tuple[str, ...]
    filename_tokens: tuple[str, ...]
    filename_digit_tokens: tuple[str, ...]
    file_kind: FileKind
    header_type: Optional[str] = None
    filename_extension: str = ""
    filename_archive_type: Optional[str] = None
    filename_volume_index: Optional[int] = None
    filename_is_root: bool = False
    filename_is_continuation: bool = False
    last_bucket: Optional[CandidateBucket] = None
    last_error_kind: str = ""
    last_error_message: str = ""
    last_missing_volume_names: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AttemptRecord:
    """A single action and outcome recorded during processing."""

    stage: str
    target: str
    action: str
    outcome: str
    message: str = ""


@dataclass(slots=True)
class ExtractionGroupResult:
    """Result of one multipart solving attempt."""

    root_path: str
    member_paths: list[str] = field(default_factory=list)
    extracted_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "failed"

    @property
    def success(self) -> bool:
        """Whether the multipart group finished successfully."""

        return self.status == "success"


@dataclass(slots=True)
class WorkspacePromotionResult:
    """Summary of promoting published output back into the workspace."""

    success: bool
    workspace_dir: str
    output_dir: str
    moved_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessLogEntry:
    """One structured log record captured during extraction."""

    level: str
    message: str


@dataclass(slots=True)
class EmbeddedExtractionResult:
    """Top-level result returned by the workflow runner."""

    output_dir: str
    working_dir: str
    status: TaskStatus
    next_action: str
    scanned_files: list[str] = field(default_factory=list)
    extracted_files: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    repaired_files: list[str] = field(default_factory=list)
    root_candidates: list[str] = field(default_factory=list)
    unresolved_candidates: list[str] = field(default_factory=list)
    password_failed_candidates: list[str] = field(default_factory=list)
    file_evidences: list[FileEvidence] = field(default_factory=list)
    group_results: list[ExtractionGroupResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    process_log: list[ProcessLogEntry] = field(default_factory=list)
    discovered_passwords: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether the workflow completed without residual failures."""

        return self.status == "success"

    @property
    def partial_success(self) -> bool:
        """Whether the workflow produced output but still has leftovers."""

        return self.status == "partial_success"
