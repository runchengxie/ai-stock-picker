"""Internal candidate data models shared across ingestion modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from .contracts import InputContract, Market, PointInTimeAssurance


@dataclass(frozen=True, slots=True)
class Candidate:
    """Normalized candidate data supplied to the model and result enrichment."""

    symbol: str
    name: str
    topic: str
    score: float
    features: dict[str, object]


@dataclass(frozen=True, slots=True)
class RawManifest:
    """Raw JSON manifest and its content fingerprint."""

    path: Path
    source_name: str
    payload: dict[str, object]
    input_sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedManifest:
    """Manifest metadata after contract-specific validation."""

    market: Market
    contract: InputContract
    rows: tuple[dict[str, object], ...]
    observation_date: date
    data_cutoff: date
    generated_at: datetime
    execution_not_before: Literal["next_trading_session"] | None
    point_in_time_assurance: PointInTimeAssurance
    evidence_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateUniverse:
    """Validated, normalized candidates plus generation metadata."""

    source_name: str
    market: Market
    selection_as_of: date
    observation_date: date
    data_cutoff: date
    source_generated_at: datetime
    upstream_execution_not_before: Literal["next_trading_session"] | None
    input_contract: InputContract
    point_in_time_assurance: PointInTimeAssurance
    evidence_limitations: tuple[str, ...]
    input_sha256: str
    candidate_symbols_sha256: str
    candidates: tuple[Candidate, ...]


__all__ = [
    "Candidate",
    "CandidateUniverse",
    "RawManifest",
    "ValidatedManifest",
]
