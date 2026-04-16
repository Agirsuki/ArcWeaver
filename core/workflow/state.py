from __future__ import annotations

"""Shared pipeline state and logging capture helpers."""

from dataclasses import dataclass, field
import logging
import os

from ..extraction_types import ExtractionGroupResult, FileEvidence, ProcessLogEntry

LOGGER_NAME = "complex_unzip.pipeline"


class PipelineLogHandler(logging.Handler):
    """Capture pipeline log records into structured in-memory entries."""

    def __init__(self, sink: list[ProcessLogEntry]):
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self._sink.append(ProcessLogEntry(level=record.levelname, message=message))


@dataclass(slots=True)
class PipelineState:
    """Mutable state shared across one extraction pipeline run."""

    source_roots: list[str]
    output_dir: str
    working_dir: str
    scan_roots: list[str]
    max_depth: int
    scanned_files: set[str] = field(default_factory=set)
    successful_archive_paths: set[str] = field(default_factory=set)
    finalized_paths: set[str] = field(default_factory=set)
    source_paths: set[str] = field(default_factory=set)
    extracted_roots: list[str] = field(default_factory=list)
    root_candidates: dict[str, FileEvidence] = field(default_factory=dict)
    unresolved_candidates: dict[str, FileEvidence] = field(default_factory=dict)
    password_failed_candidates: dict[str, FileEvidence] = field(default_factory=dict)
    evidence_by_path: dict[str, FileEvidence] = field(default_factory=dict)
    group_results: list[ExtractionGroupResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    process_log: list[ProcessLogEntry] = field(default_factory=list)
    staged_final_paths: list[str] = field(default_factory=list)
    extraction_root_depths: dict[str, int] = field(default_factory=dict)
    extraction_count: int = 0
    logger: logging.Logger = field(init=False, repr=False)
    _log_handler: PipelineLogHandler = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.logger = logging.Logger(f"{LOGGER_NAME}.{id(self)}", level=logging.DEBUG)
        self.logger.propagate = False
        self._log_handler = PipelineLogHandler(self.process_log)
        self.logger.addHandler(self._log_handler)

    def close(self) -> None:
        """Detach the transient in-memory handler from the shared logger."""

        self.logger.removeHandler(self._log_handler)
        self._log_handler.close()

    def log_debug(self, message: str) -> None:
        """Emit one debug-level pipeline message."""

        self.logger.debug(message)

    def log_info(self, message: str) -> None:
        """Emit one info-level pipeline message."""

        self.logger.info(message)

    def log_warning(self, message: str) -> None:
        """Emit one warning-level pipeline message."""

        self.logger.warning(message)

    def log_error(self, message: str) -> None:
        """Emit one error-level pipeline message."""

        self.logger.error(message)

    def depth_for_path(self, path: str) -> int:
        """Return the recursive depth of a path relative to known source roots."""

        absolute_path = os.path.abspath(path)
        matched_depth = 0

        for root in self.source_roots:
            try:
                if os.path.commonpath([absolute_path, os.path.abspath(root)]) == os.path.abspath(root):
                    matched_depth = max(matched_depth, 0)
            except ValueError:
                continue

        for root, depth in self.extraction_root_depths.items():
            try:
                if os.path.commonpath([absolute_path, os.path.abspath(root)]) == os.path.abspath(root):
                    matched_depth = max(matched_depth, depth)
            except ValueError:
                continue

        return matched_depth

    def register_extracted_root(self, root_path: str, *, parent_path: str) -> int:
        """Register one extracted directory and assign its recursive depth."""

        absolute_root = os.path.abspath(root_path)
        next_depth = self.depth_for_path(parent_path) + 1
        self.extracted_roots.append(absolute_root)
        self.extraction_root_depths[absolute_root] = next_depth
        if next_depth <= self.max_depth:
            self.scan_roots.append(absolute_root)
        else:
            self.log_info(f"[recursive] depth limit reached, publish only: {absolute_root}")
        return next_depth

    def scannable_extracted_roots(self) -> list[str]:
        """Return extracted roots that are still eligible for recursive scanning."""

        ordered_roots = list(dict.fromkeys(os.path.abspath(path) for path in self.extracted_roots))
        return [
            root
            for root in ordered_roots
            if self.extraction_root_depths.get(root, 1) <= self.max_depth
        ]
