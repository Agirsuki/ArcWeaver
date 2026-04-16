from __future__ import annotations

"""递归解压阶段的结果落账和候选路由。"""

import os
import re
import shutil

from ..archive_backend import ArchiveAttemptResult
from ..extraction_types import FileEvidence
from ..path_ops import unique_path
from ..signatures import is_archive_kind
from .state import PipelineState


def mark_success(
    state: PipelineState,
    evidence: FileEvidence,
    attempt: ArchiveAttemptResult,
) -> None:
    """记录一次成功解压，并把产物加入下一轮扫描。"""

    state.extraction_count += 1
    state.successful_archive_paths.add(evidence.source_path)
    state.source_paths.add(evidence.source_path)
    state.register_extracted_root(
        attempt.output_dir,
        parent_path=evidence.source_path,
    )
    state.root_candidates.pop(evidence.source_path, None)
    state.unresolved_candidates.pop(evidence.source_path, None)
    state.password_failed_candidates.pop(evidence.source_path, None)


def mark_password_failure(
    state: PipelineState,
    evidence: FileEvidence,
    attempt: ArchiveAttemptResult,
) -> None:
    """记录密码错误，等待调用方补充密码后再重试。"""

    _write_back_archive_hints(
        evidence=evidence,
        target_result=attempt,
    )
    evidence.last_bucket = "password_error"
    evidence.last_error_kind = attempt.status
    evidence.last_error_message = attempt.message
    state.password_failed_candidates[evidence.source_path] = evidence
    state.root_candidates.pop(evidence.source_path, None)
    state.unresolved_candidates.pop(evidence.source_path, None)
    state.errors.append(attempt.message)


def mark_final_non_archive(state: PipelineState, evidence: FileEvidence) -> None:
    """把确认是最终文件的内容纳入发布范围。"""

    if _is_within_any(evidence.source_path, state.extracted_roots):
        final_path = _repair_extracted_file_extension(evidence)
    else:
        final_path = _stage_source_file_copy(state, evidence)
    state.finalized_paths.add(final_path)
    evidence.last_bucket = "final"
    state.log_debug(f"[recursive] finalize non-archive {final_path}")


def route_failed_file(
    state: PipelineState,
    evidence: FileEvidence,
    attempts: list[ArchiveAttemptResult],
) -> None:
    """根据失败类型把文件送到主卷候选或普通候选集合。"""

    last_result = attempts[-1] if attempts else None
    missing_result = next(
        (attempt for attempt in attempts if attempt.status == "missing_volume"),
        None,
    )
    target_result = missing_result or last_result
    if target_result is None:
        return

    _write_back_archive_hints(
        evidence=evidence,
        target_result=target_result,
    )
    evidence.last_error_kind = target_result.status
    evidence.last_error_message = target_result.message
    evidence.last_missing_volume_names = tuple(target_result.missing_volumes)

    if missing_result is not None:
        evidence.last_bucket = "root"
        state.root_candidates[evidence.source_path] = evidence
        state.unresolved_candidates.pop(evidence.source_path, None)
        state.log_debug(f"[recursive] root candidate {evidence.source_path}")
        return

    evidence.last_bucket = "unresolved"
    state.unresolved_candidates[evidence.source_path] = evidence
    state.root_candidates.pop(evidence.source_path, None)
    state.log_debug(f"[recursive] unresolved candidate {evidence.source_path}")


def _write_back_archive_hints(
    *,
    evidence: FileEvidence,
    target_result: ArchiveAttemptResult,
) -> None:
    """Persist archive container hints learned from forced/header probe attempts."""

    if not _should_persist_archive_hint(target_result):
        return

    inferred_type = _infer_archive_type_from_attempt(
        evidence=evidence,
        target_result=target_result,
    )
    if not inferred_type:
        return

    if _is_header_probe_attempt(evidence, target_result):
        evidence.header_type = inferred_type
        if target_result.status == "missing_volume" and not evidence.filename_archive_type:
            evidence.filename_archive_type = inferred_type
        evidence.notes.append(f"probe_header_type:{inferred_type}")
        return

    if _is_forced_probe_attempt(evidence, target_result):
        evidence.filename_archive_type = inferred_type
        evidence.notes.append(f"probe_filename_archive_type:{inferred_type}")
        return

    if not evidence.filename_archive_type:
        evidence.filename_archive_type = inferred_type
        evidence.notes.append(f"derived_filename_archive_type:{inferred_type}")


def _should_persist_archive_hint(target_result: ArchiveAttemptResult) -> bool:
    """Return whether one attempt result is strong enough to persist hint data."""

    return target_result.status in {"success", "missing_volume", "password_error"}


def _infer_archive_type_from_attempt(
    *,
    evidence: FileEvidence,
    target_result: ArchiveAttemptResult,
) -> str | None:
    """Infer the archive container hinted by one recursive extraction attempt."""

    archive_type = (target_result.archive_type or "").strip().lower()
    if is_archive_kind(archive_type):
        return archive_type

    if target_result.archive_path == evidence.source_path:
        return None

    extension = os.path.splitext(target_result.archive_path)[1].lower().lstrip(".")
    if is_archive_kind(extension):
        return extension
    return None


def _is_forced_probe_attempt(
    evidence: FileEvidence,
    target_result: ArchiveAttemptResult,
) -> bool:
    """Return whether the attempt used a forced-extension probe alias."""

    if target_result.archive_path == evidence.source_path:
        return False
    return bool(
        re.search(
            r"\.__forced(?:_\d+)?\.[^.]+$",
            os.path.basename(target_result.archive_path),
            flags=re.IGNORECASE,
        )
    )


def _is_header_probe_attempt(
    evidence: FileEvidence,
    target_result: ArchiveAttemptResult,
) -> bool:
    """Return whether the attempt used a header-based probe alias."""

    if target_result.archive_path == evidence.source_path:
        return False
    return bool(
        re.search(
            r"\.__header(?:_\d+)?\.[^.]+$",
            os.path.basename(target_result.archive_path),
            flags=re.IGNORECASE,
        )
    )


def _repair_extracted_file_extension(evidence: FileEvidence) -> str:
    """对已确认类型的最终文件补齐正确后缀。"""

    if not evidence.header_type:
        return evidence.source_path
    expected_extension = f".{evidence.header_type.lower()}"
    current_extension = os.path.splitext(evidence.source_path)[1].lower()
    if current_extension == expected_extension:
        return evidence.source_path
    base_path, _current_extension = os.path.splitext(evidence.source_path)
    repaired_path = unique_path(f"{base_path}{expected_extension}")
    try:
        os.rename(evidence.source_path, repaired_path)
    except OSError:
        evidence.notes.append(f"repair_extension_failed:{expected_extension}")
        return evidence.source_path
    evidence.notes.append(f"repaired_extension:{expected_extension}")
    return repaired_path


def _stage_source_file_copy(state: PipelineState, evidence: FileEvidence) -> str:
    """把源目录里的最终文件复制到最终发布暂存区。"""

    expected_extension = (
        f".{evidence.header_type.lower()}"
        if evidence.header_type
        else os.path.splitext(evidence.source_path)[1]
    )
    staged_dir = os.path.join(state.working_dir, "finalized")
    os.makedirs(staged_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(evidence.source_path))[0]
    staged_path = unique_path(os.path.join(staged_dir, f"{base_name}{expected_extension}"))
    shutil.copy2(evidence.source_path, staged_path)
    state.staged_final_paths.append(staged_path)
    if staged_path != evidence.source_path:
        evidence.notes.append(f"staged_final:{staged_path}")
    return staged_path


def _is_within_any(path: str, roots: list[str]) -> bool:
    """判断文件是否来自某个已解压输出目录。"""

    absolute_path = os.path.abspath(path)
    for root in roots:
        try:
            if os.path.commonpath([absolute_path, os.path.abspath(root)]) == os.path.abspath(root):
                return True
        except ValueError:
            continue
    return False
