from __future__ import annotations

"""递归解压阶段。"""

from dataclasses import dataclass
import os
import shutil
from uuid import uuid4

from ..archive_backend import ArchiveAttemptResult, extract_archive
from ..extraction_types import EmbeddedExtractionConfig, FileEvidence
from ..polyglot import carve_hidden_archive
from ..signatures import is_archive_kind
from .recursive_evidence import build_file_evidence
from .recursive_finalize import (
    mark_final_non_archive,
    mark_password_failure,
    mark_success,
    route_failed_file,
)
from .state import PipelineState


@dataclass(slots=True)
class RecursiveExtractionPassResult:
    """递归解压阶段一次扫描轮次的结果。"""

    new_extractions: int = 0


def run_recursive_extraction_pass(
    state: PipelineState,
    *,
    config: EmbeddedExtractionConfig,
    file_paths: list[str],
) -> RecursiveExtractionPassResult:
    """顺序检查本轮文件，并处理能直接判断的解压机会。"""

    result = RecursiveExtractionPassResult()

    for file_path in file_paths:
        absolute_path = os.path.abspath(file_path)
        if not os.path.isfile(absolute_path):
            continue
        if absolute_path in state.scanned_files:
            continue

        state.scanned_files.add(absolute_path)
        evidence = build_file_evidence(absolute_path)
        state.evidence_by_path[absolute_path] = evidence
        state.log_debug(f"[recursive] inspect {absolute_path}")

        if _process_file_for_recursive_extraction(
            state=state,
            config=config,
            evidence=evidence,
        ):
            result.new_extractions += 1

    return result


def _process_file_for_recursive_extraction(
    *,
    state: PipelineState,
    config: EmbeddedExtractionConfig,
    evidence: FileEvidence,
) -> bool:
    """按既定顺序尝试文件名、文件头、Polyglot 和强制探测。"""

    attempt_results: list[ArchiveAttemptResult] = []

    if evidence.filename_archive_type:
        direct_result = _attempt_archive_extraction(
            state=state,
            config=config,
            source_path=evidence.source_path,
            archive_path=evidence.source_path,
            label="direct",
        )
        if direct_result.success:
            mark_success(state, evidence, direct_result)
            return True
        attempt_results.append(direct_result)
        if direct_result.status == "password_error":
            mark_password_failure(state, evidence, direct_result)
            return False

    if config.detect_disguised_archives and is_archive_kind(evidence.header_type):
        archive_type = evidence.header_type or evidence.filename_archive_type or "7z"
        if not _path_has_extension(evidence.source_path, archive_type):
            header_alias_path = _build_probe_alias(
                source_path=evidence.source_path,
                working_dir=os.path.join(state.working_dir, "probes"),
                extension=archive_type,
                suffix="header",
            )
            header_result = _attempt_archive_extraction(
                state=state,
                config=config,
                source_path=evidence.source_path,
                archive_path=header_alias_path,
                label=f"header:{archive_type}",
            )
            _remove_if_exists(header_alias_path)
            if header_result.success:
                mark_success(state, evidence, header_result)
                return True
            attempt_results.append(header_result)
            if header_result.status == "password_error":
                mark_password_failure(state, evidence, header_result)
                return False

    if evidence.file_kind == "non_archive" and config.detect_polyglot_archives:
        polyglot_hit = carve_hidden_archive(
            evidence.source_path,
            os.path.join(state.working_dir, "polyglot"),
            passwords=config.passwords,
            seven_zip_path=config.seven_zip_path,
        )
        if polyglot_hit is not None:
            polyglot_result = _attempt_archive_extraction(
                state=state,
                config=config,
                source_path=evidence.source_path,
                archive_path=polyglot_hit.carved_path,
                label=f"polyglot:{polyglot_hit.archive_type}",
            )
            if polyglot_result.success:
                mark_success(state, evidence, polyglot_result)
                return True
            attempt_results.append(polyglot_result)
            if polyglot_result.status == "password_error":
                mark_password_failure(state, evidence, polyglot_result)
                return False

    if evidence.file_kind != "archive":
        for extension in config.force_probe_extensions:
            if _path_has_extension(evidence.source_path, extension):
                continue
            forced_alias_path = _build_probe_alias(
                source_path=evidence.source_path,
                working_dir=os.path.join(state.working_dir, "forced_extension_probe"),
                extension=extension,
                suffix="forced",
            )
            forced_result = _attempt_archive_extraction(
                state=state,
                config=config,
                source_path=evidence.source_path,
                archive_path=forced_alias_path,
                label=f"forced:{extension}",
            )
            _remove_if_exists(forced_alias_path)
            if forced_result.success:
                mark_success(state, evidence, forced_result)
                return True
            attempt_results.append(forced_result)
            if forced_result.status == "password_error":
                mark_password_failure(state, evidence, forced_result)
                return False

    if evidence.file_kind == "non_archive":
        mark_final_non_archive(state, evidence)
        return False

    route_failed_file(state, evidence, attempt_results)
    return False


def _attempt_archive_extraction(
    *,
    state: PipelineState,
    config: EmbeddedExtractionConfig,
    source_path: str,
    archive_path: str,
    label: str,
) -> ArchiveAttemptResult:
    """调用 7-Zip 执行一次实际解压尝试。"""

    extract_dir = os.path.join(
        state.working_dir,
        "extracted",
        f"{uuid4().hex[:12]}_{os.path.splitext(os.path.basename(source_path))[0] or 'archive'}",
    )
    state.log_debug(f"[recursive] try {label} -> {archive_path}")
    attempt = extract_archive(
        archive_path,
        extract_dir,
        passwords=config.passwords,
        seven_zip_path=config.seven_zip_path,
    )
    if attempt.success:
        state.log_debug(f"[recursive] success: {archive_path}")
        return attempt

    shutil.rmtree(extract_dir, ignore_errors=True)
    if attempt.status == "missing_volume":
        state.log_debug(f"[recursive] {attempt.status}: {attempt.message}")
    else:
        state.log_debug(f"[recursive] {attempt.status}: {attempt.message}")
    return attempt


def _build_probe_alias(
    *,
    source_path: str,
    working_dir: str,
    extension: str,
    suffix: str,
) -> str:
    """为探测尝试创建一个临时别名文件。"""

    os.makedirs(working_dir, exist_ok=True)
    base_name = os.path.basename(source_path)
    alias_name = f"{base_name}.__{suffix}.{extension.lstrip('.')}"
    alias_path = os.path.join(working_dir, alias_name)
    unique_alias_path = _ensure_unique_probe_path(alias_path)
    shutil.copy2(source_path, unique_alias_path)
    return unique_alias_path


def _path_has_extension(path: str, extension: str) -> bool:
    """判断文件当前后缀是否已经和目标类型一致。"""

    return os.path.splitext(path)[1].lower() == f".{extension.lower().lstrip('.')}"


def _ensure_unique_probe_path(path: str) -> str:
    """避免探测别名和历史残留文件撞名。"""

    if not os.path.exists(path):
        return path

    directory, filename = os.path.split(path)
    stem, extension = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{counter}{extension}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _remove_if_exists(path: str) -> None:
    """删除探测阶段留下的临时文件。"""

    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
