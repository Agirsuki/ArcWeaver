from __future__ import annotations

"""递归解压阶段的文件证据提取。"""

import os

from ..extraction_types import FileEvidence
from ..family import build_family_identity
from ..signatures import detect_file_signature, is_archive_kind


def build_file_evidence(file_path: str) -> FileEvidence:
    """从文件名、文件头和大小生成候选判断所需的证据。"""

    family = build_family_identity(file_path)
    signature = detect_file_signature(file_path)
    size_bytes = os.path.getsize(file_path)
    return FileEvidence(
        source_path=file_path,
        display_name=family.display_name,
        size_bytes=size_bytes,
        family_stem=family.family_stem,
        family_core=family.family_core,
        normalized_family=family.normalized_family,
        family_tokens=family.family_tokens,
        digit_tokens=family.digit_tokens,
        filename_tokens=family.filename_tokens,
        filename_digit_tokens=family.filename_digit_tokens,
        file_kind=signature_file_kind(signature.kind if signature else None),
        header_type=signature.kind if signature else None,
        filename_extension=family.filename_extension,
        filename_archive_type=family.archive_hint.archive_type or family.cloaked_archive_type,
        filename_volume_index=family.archive_hint.volume_index,
        filename_is_root=family.archive_hint.is_root,
        filename_is_continuation=family.archive_hint.is_continuation,
    )


def signature_file_kind(kind: str | None) -> str:
    """把签名类型简化成 archive / non_archive / unknown 三类。"""

    if is_archive_kind(kind):
        return "archive"
    if kind:
        return "non_archive"
    return "unknown"
