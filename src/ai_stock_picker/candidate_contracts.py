"""Versioned candidate-manifest contract detection and validation."""

from __future__ import annotations

from datetime import date
from typing import cast

from .candidate_models import RawManifest, ValidatedManifest
from .contracts import Market
from .hot_sector_v1 import validate_hot_sector_manifest
from .time_utils import parse_cutoff_date, parse_date, parse_timestamp

_GENERIC_IDENTITY = ("1.0.0", "stock_candidate_universe")
_HOT_IDENTITY = ("1.0.0", "hot_sector_candidate_universe")
_GENERIC_LIMITATIONS = (
    "candidate_manifest_does_not_establish_strict_point_in_time",
    "candidate_manifest_does_not_establish_out_of_sample_validity",
)


def validate_candidate_manifest(
    raw: RawManifest, *, selection_as_of: date
) -> ValidatedManifest:
    """Detect and validate a supported versioned candidate contract."""

    payload = raw.payload
    market = _parse_market(payload.get("market"))
    identity = (payload.get("schema_version"), payload.get("artifact_type"))
    if identity == _GENERIC_IDENTITY:
        rows = _require_rows(payload, "candidates")
        contract = "stock_candidate_universe_v1"
    elif identity == _HOT_IDENTITY and market == "CN":
        rows = _require_rows(payload, "candidate_universe")
        contract = "hot_sector_candidate_universe_v1"
    else:
        raise ValueError(f"unsupported candidate contract identity: {identity!r}")

    observation_date = _manifest_observation_date(payload)
    if observation_date > selection_as_of:
        raise ValueError("manifest observation date is after selection --as-of")
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    data_cutoff = parse_cutoff_date(payload.get("data_cutoff"))
    if data_cutoff > observation_date:
        raise ValueError("manifest data_cutoff is after its observation date")
    universe_size = payload.get("universe_size")
    if isinstance(universe_size, bool) or not isinstance(universe_size, int):
        raise ValueError("manifest universe_size must be an integer")
    if universe_size != len(rows):
        raise ValueError("manifest universe_size does not equal candidate row count")
    if not rows:
        raise ValueError("candidate universe is empty")
    if len(rows) > 1000:
        raise ValueError("candidate universe exceeds the 1000-row prompt safety limit")

    execution_not_before = None
    assurance = "unverified"
    limitations = _GENERIC_LIMITATIONS
    if contract == "hot_sector_candidate_universe_v1":
        limitations, execution_not_before = validate_hot_sector_manifest(
            payload, rows, observation_date, generated_at
        )
        assurance = "signal_date_only"
    elif payload.get("execution_not_before") == "next_trading_session":
        execution_not_before = "next_trading_session"

    return ValidatedManifest(
        market=market,
        contract=contract,
        rows=rows,
        observation_date=observation_date,
        data_cutoff=data_cutoff,
        generated_at=generated_at,
        execution_not_before=execution_not_before,
        point_in_time_assurance=assurance,
        evidence_limitations=limitations,
    )


def _parse_market(value: object) -> Market:
    if value not in {"CN", "US"}:
        raise ValueError("manifest market must be CN or US")
    return cast(Market, value)


def _require_rows(
    payload: dict[str, object], field: str
) -> tuple[dict[str, object], ...]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"manifest {field} must be an array of objects")
    return tuple(cast(dict[str, object], row) for row in value)


def _manifest_observation_date(payload: dict[str, object]) -> date:
    raw_date = payload.get("observation_date", payload.get("date"))
    if not isinstance(raw_date, str):
        raise ValueError("manifest observation_date is required")
    observation_date = parse_date(raw_date)
    raw_date_int = payload.get("date_int")
    if raw_date_int is not None and str(raw_date_int) != observation_date.strftime(
        "%Y%m%d"
    ):
        raise ValueError("manifest date_int does not match observation_date")
    return observation_date


__all__ = ["validate_candidate_manifest"]
