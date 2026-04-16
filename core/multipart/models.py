from __future__ import annotations

"""Shared dataclasses used by multipart scoring and solving."""

from dataclasses import dataclass, field

from ..extraction_types import FileEvidence


@dataclass(slots=True, frozen=True)
class ScoreComponent:
    """One scored factor together with its configured weight and contribution."""

    name: str
    weight: float
    raw_value: float
    contribution: float
    detail: str = ""


@dataclass(slots=True, frozen=True)
class ScoreBreakdown:
    """A bundle of score components and the final accumulated score."""

    total: float = 0.0
    components: tuple[ScoreComponent, ...] = ()


@dataclass(slots=True, frozen=True)
class BootstrapPolicy:
    """Derived limits used by the first multipart bootstrap selection."""

    mean_score: float
    leader_score: float
    min_score: float
    max_score_gap: float
    candidate_cap: int
    unresolved_count: int
    root_count: int


@dataclass(slots=True)
class CandidateScore:
    """A candidate file together with the score assigned to it."""

    evidence: FileEvidence
    score: float
    base_score: float = 0.0
    bonus_score: float = 0.0
    base_components: tuple[ScoreComponent, ...] = ()
    bonus_components: tuple[ScoreComponent, ...] = ()

    @property
    def all_components(self) -> tuple[ScoreComponent, ...]:
        """Return the full score detail in the same order it was computed."""

        return self.base_components + self.bonus_components


@dataclass(slots=True)
class RootPriorityScore:
    """Priority score assigned to a root candidate before solving."""

    evidence: FileEvidence
    score: float
    components: tuple[ScoreComponent, ...] = field(default_factory=tuple)
