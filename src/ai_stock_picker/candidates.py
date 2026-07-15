"""Public candidate-manifest loading facade."""

from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

from .candidate_contracts import validate_candidate_manifest
from .candidate_io import read_candidate_manifest
from .candidate_models import Candidate, CandidateUniverse
from .candidate_normalization import normalize_candidates


def load_candidate_universe(path: str | Path, *, as_of: date) -> CandidateUniverse:
    """Load a versioned manifest and return normalized candidates."""

    raw = read_candidate_manifest(path)
    manifest = validate_candidate_manifest(raw, selection_as_of=as_of)
    candidates = normalize_candidates(manifest)
    symbols = sorted(candidate.symbol for candidate in candidates)
    symbol_hash = sha256(
        json.dumps(symbols, separators=(",", ":")).encode()
    ).hexdigest()
    return CandidateUniverse(
        source_name=raw.source_name,
        market=manifest.market,
        selection_as_of=as_of,
        observation_date=manifest.observation_date,
        data_cutoff=manifest.data_cutoff,
        source_generated_at=manifest.generated_at,
        upstream_execution_not_before=manifest.execution_not_before,
        input_contract=manifest.contract,
        point_in_time_assurance=manifest.point_in_time_assurance,
        evidence_limitations=manifest.evidence_limitations,
        input_sha256=raw.input_sha256,
        candidate_symbols_sha256=symbol_hash,
        candidates=candidates,
    )


__all__ = ["Candidate", "CandidateUniverse", "load_candidate_universe"]
