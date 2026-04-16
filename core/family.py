from __future__ import annotations

"""Filename identity helpers used by multipart discovery and scoring."""

from dataclasses import dataclass
import os
import re


_PROBE_SUFFIX_RE = re.compile(r"\.__(?:forced|probe|polyglot(?:_\d+)?)\.[^.]+$", re.IGNORECASE)
_ARCHIVE_SUFFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.tar\.zst$", re.IGNORECASE),
    re.compile(r"\.tar\.gz$", re.IGNORECASE),
    re.compile(r"\.tar\.bz2$", re.IGNORECASE),
    re.compile(r"\.tar\.xz$", re.IGNORECASE),
    re.compile(r"\.part\d+\.rar$", re.IGNORECASE),
    re.compile(r"\.(7z|zip)\.\d{3}$", re.IGNORECASE),
    re.compile(r"\.(rar|7z|zip|tar|gz|bz2|xz|zst|pdf|mp4|mkv|avi|jpg|jpeg|png|gif|webp|mp3|wav|flac|ogg)$", re.IGNORECASE),
    re.compile(r"\.(z\d{2}|r\d{2})$", re.IGNORECASE),
)
_TOKEN_RE = re.compile(r"[A-Za-z]+\d*|\d+|[\u3400-\u4dbf\u4e00-\u9fff]+")
_TRAILING_INDEX_PARENS_RE = re.compile(r"^(.*?)[\s._-]*[\(\[（]\s*(\d+)\s*[\)\]）]$")
_TRAILING_INDEX_SEPARATOR_RE = re.compile(r"^(.*?)[\s._-]+(\d+)$")


@dataclass(frozen=True, slots=True)
class ArchiveNameHint:
    """Multipart clues inferred directly from a file name."""

    archive_type: str | None
    volume_index: int | None
    is_multipart: bool
    is_root: bool
    is_continuation: bool


@dataclass(frozen=True, slots=True)
class FamilyIdentity:
    """Normalized identity used for family matching and scoring."""

    display_name: str
    family_stem: str
    family_core: str
    normalized_family: str
    family_tokens: tuple[str, ...]
    digit_tokens: tuple[str, ...]
    filename_tokens: tuple[str, ...]
    filename_digit_tokens: tuple[str, ...]
    filename_extension: str
    archive_hint: ArchiveNameHint
    cloaked_archive_type: str | None

    @property
    def tokens(self) -> tuple[str, ...]:
        """Backward-compatible alias for the normalized family tokens."""

        return self.family_tokens


def build_family_identity(path_or_name: str) -> FamilyIdentity:
    """Build a normalized family identity from a path or display name."""

    display_name = os.path.basename(path_or_name.rstrip("\\/")) or path_or_name
    archive_hint = detect_archive_name_hint(display_name)
    family_stem = derive_family_stem(display_name)
    family_core = derive_family_core(family_stem)
    family_tokens = tuple(tokenize_filename_parts(family_core))
    filename_tokens = tuple(tokenize_filename_parts(display_name))
    return FamilyIdentity(
        display_name=display_name,
        family_stem=family_stem,
        family_core=family_core,
        normalized_family=normalize_family_text(family_core),
        family_tokens=family_tokens,
        digit_tokens=tuple(token for token in family_tokens if token.isdigit()),
        filename_tokens=filename_tokens,
        filename_digit_tokens=tuple(token for token in filename_tokens if token.isdigit()),
        filename_extension=os.path.splitext(display_name)[1].lower(),
        archive_hint=archive_hint,
        cloaked_archive_type=detect_cloaked_archive_type(display_name),
    )


def detect_archive_name_hint(display_name: str) -> ArchiveNameHint:
    """Infer archive and multipart hints from the visible file name."""

    lowered = display_name.lower()

    match = re.search(r"\.(7z|zip)\.(\d{3})$", lowered)
    if match:
        index = int(match.group(2))
        return ArchiveNameHint(
            archive_type=match.group(1),
            volume_index=index,
            is_multipart=True,
            is_root=index == 1,
            is_continuation=index != 1,
        )

    match = re.search(r"\.part(\d+)\.rar$", lowered)
    if match:
        index = int(match.group(1))
        return ArchiveNameHint(
            archive_type="rar",
            volume_index=index,
            is_multipart=True,
            is_root=index == 1,
            is_continuation=index != 1,
        )

    match = re.search(r"\.z(\d{2})$", lowered)
    if match:
        return ArchiveNameHint(
            archive_type="zip",
            volume_index=int(match.group(1)) + 1,
            is_multipart=True,
            is_root=False,
            is_continuation=True,
        )

    match = re.search(r"\.r(\d{2})$", lowered)
    if match:
        return ArchiveNameHint(
            archive_type="rar",
            volume_index=int(match.group(1)) + 2,
            is_multipart=True,
            is_root=False,
            is_continuation=True,
        )

    match = re.search(r"\.(7z|zip|rar|tar|gz|bz2|xz|zst)$", lowered)
    if match:
        return ArchiveNameHint(
            archive_type=match.group(1),
            volume_index=1,
            is_multipart=False,
            is_root=False,
            is_continuation=False,
        )

    return ArchiveNameHint(
        archive_type=None,
        volume_index=None,
        is_multipart=False,
        is_root=False,
        is_continuation=False,
    )


def derive_family_stem(display_name: str) -> str:
    """Strip probe tails and known archive suffixes while keeping core identity."""

    stem = display_name.strip()
    while True:
        updated = _PROBE_SUFFIX_RE.sub("", stem)
        if updated == stem:
            break
        stem = updated

    changed = True
    while changed:
        changed = False
        for pattern in _ARCHIVE_SUFFIX_PATTERNS:
            updated = pattern.sub("", stem)
            if updated != stem:
                stem = updated
                changed = True
                break

    stem = _strip_cloaked_archive_tail(stem)
    stem = stem.strip(" ._-")
    return stem or display_name


def derive_family_core(family_stem: str) -> str:
    """Collapse a family stem into the stable family core used for grouping."""

    normalized = family_stem.strip(" ._-")
    if not normalized:
        return family_stem

    for pattern in (_TRAILING_INDEX_PARENS_RE, _TRAILING_INDEX_SEPARATOR_RE):
        match = pattern.match(normalized)
        if not match:
            continue
        prefix = match.group(1).strip(" ._-")
        if prefix:
            return prefix
    return normalized


def normalize_family_text(value: str) -> str:
    """Normalize separators and casing for family comparison."""

    normalized = re.sub(r"[\s._\-]+", " ", value.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or value.strip().lower()


def family_similarity(left: FamilyIdentity, right: FamilyIdentity) -> float:
    """Return ordered token-prefix similarity between two identities."""

    return ordered_token_prefix_similarity(left.family_tokens, right.family_tokens)


def shared_token_ratio(left: FamilyIdentity, right: FamilyIdentity) -> float:
    """Return the weighted overlap ratio of ordered family tokens."""

    return weighted_token_overlap_ratio(left.family_tokens, right.family_tokens)


def tokenize_filename_parts(value: str) -> list[str]:
    """Split a file name into ordered tokens across latin, digit, and CJK runs."""

    if not value:
        return []
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(value.strip())]


def ordered_token_prefix_similarity(
    left_tokens: tuple[str, ...] | list[str],
    right_tokens: tuple[str, ...] | list[str],
) -> float:
    """Return weighted similarity of the shared ordered token prefix."""

    if not left_tokens or not right_tokens:
        return 0.0
    shared_weight = 0
    for left_token, right_token in zip(left_tokens, right_tokens):
        if left_token != right_token:
            break
        shared_weight += max(len(left_token), 1)
    total_weight = max(_token_weight(left_tokens), _token_weight(right_tokens))
    return shared_weight / total_weight if total_weight else 0.0


def weighted_token_overlap_ratio(
    left_tokens: tuple[str, ...] | list[str],
    right_tokens: tuple[str, ...] | list[str],
) -> float:
    """Return weighted overlap ratio across all ordered filename tokens."""

    if not left_tokens or not right_tokens:
        return 0.0
    remaining: dict[str, int] = {}
    for token in right_tokens:
        remaining[token] = remaining.get(token, 0) + 1
    overlap_weight = 0
    for token in left_tokens:
        count = remaining.get(token, 0)
        if count <= 0:
            continue
        overlap_weight += max(len(token), 1)
        remaining[token] = count - 1
    total_weight = _token_weight(left_tokens) + _token_weight(right_tokens) - overlap_weight
    return overlap_weight / total_weight if total_weight else 0.0


def smaller_numeric_first_difference_score(
    left_tokens: tuple[str, ...] | list[str],
    right_tokens: tuple[str, ...] | list[str],
) -> float:
    """Reward smaller numeric value at the first differing token after a shared prefix."""

    if not left_tokens or not right_tokens:
        return 0.0

    prefix_count = 0
    for left_token, right_token in zip(left_tokens, right_tokens):
        if left_token != right_token:
            break
        prefix_count += 1

    if prefix_count >= len(right_tokens):
        return 0.0

    differing_token = right_tokens[prefix_count]
    if not differing_token.isdigit():
        return 0.0

    numeric_value = int(differing_token)
    prefix_ratio = prefix_count / max(1, len(left_tokens), len(right_tokens))
    numeric_preference = 1.0 / max(1, numeric_value)
    return prefix_ratio * numeric_preference


def _token_weight(tokens: tuple[str, ...] | list[str]) -> int:
    """Return the total weight of a token sequence."""

    return sum(max(len(token), 1) for token in tokens)


def _strip_cloaked_archive_tail(value: str) -> str:
    """Drop a trailing cloaked archive marker without erasing core identity."""

    segments = re.split(r"[._\-]+", value)
    if len(segments) < 2:
        return value

    archive_tokens = ("zip", "7z", "rar")
    cleaned_segments: list[str] = []
    for segment in segments:
        lowered = segment.lower()
        if any(_flex_matches_archive_token(lowered, token) for token in archive_tokens):
            if cleaned_segments:
                return ".".join(cleaned_segments)
            return value
        cleaned_segments.append(segment)
    return value


def _flex_matches_archive_token(segment: str, token: str) -> bool:
    """Match archive token letters in order, tolerating separator-free disguises."""

    position = 0
    for character in token:
        next_position = segment.find(character, position)
        if next_position < 0:
            return False
        position = next_position + 1
    return True


def detect_cloaked_archive_type(display_name: str) -> str | None:
    """Try to infer a disguised archive type from the visible file name only."""

    segments = re.split(r"[._\-]+", display_name)
    for segment in reversed(segments):
        lowered = segment.lower()
        for token in ("zip", "7z", "rar"):
            if _flex_matches_archive_token(lowered, token):
                return token
    return None
