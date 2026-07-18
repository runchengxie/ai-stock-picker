"""Candidate-universe ingestion with explicit provenance classification."""

from __future__ import annotations

import ast
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeGuard, cast
from zoneinfo import ZoneInfo

from .contracts import (
    HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_ID,
    HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_SHA256,
    HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_VERSION,
    InputContract,
    Market,
    PointInTimeAssurance,
    validate_symbol,
)

_MAX_INPUT_BYTES = 10_000_000
HOT_SECTOR_INPUT_CONTRACTS = frozenset(
    {
        "hot_sector_candidate_universe_v1",
        "hot_sector_candidate_universe_v2",
    }
)
_SOURCE_CONCEPTS_POLICY_CORE: dict[str, object] = {
    "policy_id": HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_ID,
    "version": HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_VERSION,
    "allowed": ["theme", "concept", "related_concepts"],
    "excluded": ["tag", "lu_desc", "status", "rank_reason", "limit_type"],
    "normalizer_id": "hotsector.concept_token.v1",
}
SOURCE_CONCEPTS_POLICY_SHA256 = HOT_SECTOR_V2_SOURCE_CONCEPTS_POLICY_SHA256
_HOT_SECTOR_V2_MODEL_IDENTITY = {
    "model_id": "hotsector-theme-v3",
    "model_version": "3.0.0",
    "feature_set_id": "topic-concept-hotspot-overlay-theme-only-v1",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    """Normalized candidate data used in prompts and result enrichment."""

    symbol: str
    name: str
    topic: str
    score: float
    features: dict[str, object]


@dataclass(frozen=True, slots=True)
class CandidateUniverse:
    """Validated candidates plus their input-lineage classification."""

    path: Path
    selection_as_of: date
    observation_date: date | None
    data_cutoff: date | None
    source_generated_at: datetime | None
    upstream_execution_not_before: Literal["next_trading_session"] | None
    input_contract: InputContract
    point_in_time_assurance: PointInTimeAssurance
    evidence_limitations: tuple[str, ...]
    input_sha256: str
    candidate_symbols_sha256: str
    candidates: tuple[Candidate, ...]


def parse_date(value: str) -> date:
    """Parse YYYY-MM-DD or YYYYMMDD without accepting ambiguous formats."""

    stripped = value.strip()
    fmt = "%Y%m%d" if len(stripped) == 8 and stripped.isdigit() else "%Y-%m-%d"
    try:
        return datetime.strptime(stripped, fmt).date()
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD or YYYYMMDD") from exc


def is_hot_sector_contract(contract: InputContract) -> bool:
    """Return whether an input uses a recognized hot-sector owner contract."""

    return contract in HOT_SECTOR_INPUT_CONTRACTS


def load_candidate_universe(
    path: str | Path,
    *,
    market: Market,
    as_of: date,
) -> CandidateUniverse:
    """Load JSON manifest or legacy CSV and validate the complete candidate set."""

    candidate_path = Path(path).expanduser().resolve()
    if not candidate_path.is_file():
        raise ValueError(f"candidate input does not exist: {candidate_path}")
    raw = candidate_path.read_bytes()
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError("candidate input exceeds the 10 MB safety limit")
    input_hash = sha256(raw).hexdigest()

    observation_date: date | None
    if candidate_path.suffix.lower() == ".json":
        rows, metadata = _load_json(raw)
        contract = _detect_json_contract(metadata, market)
        observation_date, source_generated_at, data_cutoff = _validate_manifest(
            metadata, rows, as_of
        )
        if contract in HOT_SECTOR_INPUT_CONTRACTS:
            _validate_hot_sector_contract(
                metadata,
                rows,
                observation_date,
                source_generated_at,
                contract=contract,
            )
        assurance, limitations = _classify_manifest(data_cutoff, contract, metadata)
        upstream_execution_not_before: Literal["next_trading_session"] | None = (
            "next_trading_session"
            if metadata.get("execution_not_before") == "next_trading_session"
            else None
        )
    elif candidate_path.suffix.lower() == ".csv":
        rows = _load_csv(raw)
        metadata = {}
        contract = "legacy_csv"
        source_generated_at = None
        observation_date = _validate_row_dates(rows, as_of)
        data_cutoff = None
        upstream_execution_not_before = None
        assurance = "unverified"
        limitations = (
            "legacy_csv_without_manifest_timestamp",
            "data_cutoff_unavailable",
        )
    else:
        raise ValueError("candidate input must be a .json manifest or .csv file")

    if len(rows) > 1000:
        raise ValueError("candidate universe exceeds the 1000-row prompt safety limit")
    candidates = tuple(_normalize_rows(rows, market))
    if not candidates:
        raise ValueError("candidate universe is empty")
    symbols = [candidate.symbol for candidate in candidates]
    if len(symbols) != len(set(symbols)):
        duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
        raise ValueError(f"candidate symbols must be unique: {duplicates}")
    symbol_hash = sha256(
        json.dumps(sorted(symbols), separators=(",", ":")).encode()
    ).hexdigest()
    return CandidateUniverse(
        path=candidate_path,
        selection_as_of=as_of,
        observation_date=observation_date,
        data_cutoff=data_cutoff,
        source_generated_at=source_generated_at,
        upstream_execution_not_before=upstream_execution_not_before,
        input_contract=contract,
        point_in_time_assurance=assurance,
        evidence_limitations=limitations,
        input_sha256=input_hash,
        candidate_symbols_sha256=symbol_hash,
        candidates=candidates,
    )


def _load_json(raw: bytes) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid candidate JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be a versioned candidate manifest object")
    rows = payload.get("candidate_universe", payload.get("candidates"))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(
            "manifest candidate_universe/candidates must be a list of objects"
        )
    return cast(list[dict[str, object]], rows), cast(dict[str, object], payload)


def _load_csv(raw: bytes) -> list[dict[str, object]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("candidate CSV must be UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("candidate CSV has no header")
    return [dict(row) for row in reader]


def _validate_manifest(
    metadata: dict[str, object],
    rows: list[dict[str, object]],
    as_of: date,
) -> tuple[date, datetime, date | None]:
    raw_date = metadata.get(
        "observation_date", metadata.get("date", metadata.get("as_of"))
    )
    if not isinstance(raw_date, str):
        raise ValueError("manifest observation date is required")
    observation_date = parse_date(raw_date)
    if observation_date > as_of:
        raise ValueError("manifest observation date is after selection --as-of")
    raw_date_int = metadata.get("date_int")
    if raw_date_int is not None and str(raw_date_int) != observation_date.strftime(
        "%Y%m%d"
    ):
        raise ValueError("manifest date_int does not match observation date")
    universe_size = metadata.get("universe_size")
    if isinstance(universe_size, bool) or not isinstance(universe_size, int):
        raise ValueError("manifest universe_size must be an integer")
    if universe_size != len(rows):
        raise ValueError("manifest universe_size does not equal candidate row count")
    generated_at = _parse_timestamp(metadata.get("generated_at"), "generated_at")
    cutoff_raw = metadata.get("data_cutoff")
    data_cutoff = _parse_cutoff_date(cutoff_raw) if cutoff_raw is not None else None
    if data_cutoff is not None and data_cutoff > observation_date:
        raise ValueError("manifest data_cutoff is after its observation date")
    return observation_date, generated_at, data_cutoff


def _detect_json_contract(metadata: dict[str, object], market: Market) -> InputContract:
    schema_version = metadata.get("schema_version")
    artifact_type = metadata.get("artifact_type")
    declared_market = metadata.get("market")
    if schema_version is None and artifact_type is None:
        if declared_market is not None and declared_market != market:
            raise ValueError("manifest market does not match requested market")
        return "generic_json_manifest"
    actual = (schema_version, artifact_type, declared_market)
    if market != "CN" or artifact_type != "hot_sector_candidate_universe":
        raise ValueError(f"unsupported candidate contract identity: {actual!r}")
    if schema_version == "1.0.0" and declared_market == "CN":
        return "hot_sector_candidate_universe_v1"
    if schema_version == "2.0.0" and declared_market == "CN":
        return "hot_sector_candidate_universe_v2"
    raise ValueError(f"unsupported candidate contract identity: {actual!r}")


def _validate_hot_sector_contract(
    metadata: dict[str, object],
    rows: list[dict[str, object]],
    observation_date: date,
    generated_at: datetime,
    *,
    contract: InputContract,
) -> None:
    if not isinstance(metadata.get("candidate_universe"), list):
        raise ValueError("hot-sector candidate_universe must be an array")
    expected_date, temporal_context = _validate_hot_temporal_metadata(
        metadata, observation_date, generated_at
    )
    _validate_hot_payload(metadata, rows, contract=contract)
    if contract == "hot_sector_candidate_universe_v2":
        _validate_hot_sector_v2(metadata)
    _validate_hot_provenance(metadata, expected_date)
    _validate_hot_evidence(metadata, temporal_context)


def _validate_hot_temporal_metadata(
    metadata: dict[str, object],
    observation_date: date,
    generated_at: datetime,
) -> tuple[str, Literal["same_day_eod_generation", "post_observation_generation"]]:
    expected_date = observation_date.strftime("%Y%m%d")
    date_values = (
        metadata.get("date"),
        metadata.get("date_int"),
        metadata.get("observation_date"),
        metadata.get("data_cutoff"),
    )
    try:
        normalized_dates = {
            parse_date(str(value)).strftime("%Y%m%d") for value in date_values
        }
    except ValueError as exc:
        raise ValueError(
            "hot-sector contract dates must be valid and complete"
        ) from exc
    if normalized_dates != {expected_date}:
        raise ValueError(
            "hot-sector contract date fields must all equal observation_date"
        )
    if metadata.get("data_cutoff_semantics") != "end_of_day":
        raise ValueError("hot-sector data_cutoff_semantics must be end_of_day")
    if metadata.get("execution_not_before") != "next_trading_session":
        raise ValueError("hot-sector execution_not_before must be next_trading_session")
    if metadata.get("future_data_included") is not False:
        raise ValueError("hot-sector future_data_included must be false")

    generated_local = generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if generated_local.date() < observation_date or (
        generated_local.date() == observation_date
        and generated_local.timetz().replace(tzinfo=None) < time(16, 0)
    ):
        raise ValueError("hot-sector generated_at precedes the completed EOD cutoff")
    temporal_context: Literal[
        "same_day_eod_generation", "post_observation_generation"
    ] = (
        "same_day_eod_generation"
        if generated_local.date() == observation_date
        else "post_observation_generation"
    )
    return expected_date, temporal_context


def _validate_hot_payload(
    metadata: dict[str, object],
    rows: list[dict[str, object]],
    *,
    contract: InputContract,
) -> None:
    topics = metadata.get("topics")
    if not isinstance(topics, list):
        raise ValueError("hot-sector topics must be an array")
    for topic in topics:
        _validate_hot_topic(topic)
    for field in ("data_sources", "config_snapshot"):
        if not isinstance(metadata.get(field), dict):
            raise ValueError(f"hot-sector {field} must be an object")
    for row in rows:
        _validate_hot_candidate_row(row, contract=contract)


def _validate_hot_topic(value: object) -> None:
    fields = {"topic", "weight", "reasoning", "related_concepts", "source_signals"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("hot-sector topic must use the exact topic schema")
    topic = cast(dict[str, object], value)
    name = topic.get("topic")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("hot-sector topic.topic must be non-empty")
    weight = topic.get("weight")
    if not _is_finite_number(weight) or not 0.0 <= float(weight) <= 1.0:
        raise ValueError("hot-sector topic.weight must be finite in [0, 1]")
    if not isinstance(topic.get("reasoning"), str):
        raise ValueError("hot-sector topic.reasoning must be a string")
    for field in ("related_concepts", "source_signals"):
        _require_nonempty_string_array(topic.get(field), f"topic.{field}")


def _validate_hot_candidate_row(
    row: dict[str, object], *, contract: InputContract
) -> None:
    name = row.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
        raise ValueError("hot-sector candidate name must be 1-64 characters")
    if not _is_finite_number(row.get("score")):
        raise ValueError("hot-sector candidate score must be finite")
    relevance = row.get("relevance")
    if not _is_finite_number(relevance) or not 0.0 <= float(relevance) <= 1.0:
        raise ValueError("hot-sector candidate relevance must be finite in [0, 1]")
    for field in ("source_topics", "source_concepts"):
        values = row.get(field)
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            raise ValueError(f"candidate {field} must be an array of non-empty strings")
    if contract == "hot_sector_candidate_universe_v2":
        for field in (
            "source_event_tags",
            "source_event_statuses",
            "source_event_reasons",
        ):
            values = row.get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(
                    f"candidate {field} must be an array of non-empty strings"
                )


def _validate_hot_sector_v2(metadata: dict[str, object]) -> None:
    policy = _required_object(metadata, "source_concepts_policy")
    expected = {
        **_SOURCE_CONCEPTS_POLICY_CORE,
        "canonical_sha256": SOURCE_CONCEPTS_POLICY_SHA256,
    }
    if policy != expected:
        raise ValueError("hot-sector source_concepts_policy is not canonical")
    canonical = json.dumps(
        _SOURCE_CONCEPTS_POLICY_CORE,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if sha256(canonical).hexdigest() != SOURCE_CONCEPTS_POLICY_SHA256:
        raise RuntimeError("source_concepts policy digest constant is inconsistent")
    if _required_object(metadata, "model_identity") != _HOT_SECTOR_V2_MODEL_IDENTITY:
        raise ValueError("hot-sector model_identity is not canonical")


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(float(value))
    )


def _require_nonempty_string_array(value: object, field: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"hot-sector {field} must be a non-empty string array")


def _validate_hot_provenance(metadata: dict[str, object], expected_date: str) -> None:
    provenance = _required_object(metadata, "provenance")
    if provenance.get("timezone") != "Asia/Shanghai":
        raise ValueError("hot-sector provenance.timezone must be Asia/Shanghai")
    if str(provenance.get("observation_date")) != expected_date:
        raise ValueError("hot-sector provenance.observation_date is inconsistent")
    if str(provenance.get("data_cutoff")) != expected_date:
        raise ValueError("hot-sector provenance.data_cutoff is inconsistent")
    if provenance.get("future_data_included") is not False:
        raise ValueError("hot-sector provenance must exclude future data")
    if provenance.get("artifact_role") != "candidate_universe":
        raise ValueError("hot-sector provenance.artifact_role is invalid")
    if provenance.get("strict_point_in_time") is not False:
        raise ValueError("hot-sector provenance cannot claim strict point-in-time")
    rotation = _required_object(provenance, "rotation")
    provenance_level = rotation.get("provenance_level")
    if provenance_level not in {"signal_date_only", "unavailable"}:
        raise ValueError("hot-sector rotation provenance_level is invalid")
    if rotation.get("strict_point_in_time") is not False:
        raise ValueError("hot-sector rotation cannot claim strict point-in-time")
    if rotation.get("publisher_receipt_verified") is not False:
        raise ValueError("hot-sector rotation cannot claim a publisher receipt")
    try:
        as_of_date = parse_date(str(rotation.get("as_of_date")))
    except ValueError as exc:
        raise ValueError("hot-sector rotation.as_of_date must be a valid date") from exc
    if as_of_date.strftime("%Y%m%d") != expected_date:
        raise ValueError("hot-sector rotation.as_of_date must match observation_date")
    signal_date_value = rotation.get("signal_date")
    signal_date: date | None = None
    if signal_date_value is not None:
        try:
            signal_date = parse_date(str(signal_date_value))
        except ValueError as exc:
            raise ValueError(
                "hot-sector rotation.signal_date must be a valid date or null"
            ) from exc
        if signal_date > as_of_date:
            raise ValueError(
                "hot-sector rotation.signal_date must not exceed as_of_date"
            )
    if provenance_level == "signal_date_only" and signal_date is None:
        raise ValueError("hot-sector signal_date_only rotation requires signal_date")
    if provenance_level == "unavailable" and signal_date_value is not None:
        raise ValueError("hot-sector unavailable rotation requires a null signal_date")


def _validate_hot_evidence(
    metadata: dict[str, object],
    expected_context: Literal["same_day_eod_generation", "post_observation_generation"],
) -> None:
    evidence = _required_object(metadata, "evidence")
    if evidence.get("strict_point_in_time") is not False:
        raise ValueError("hot-sector evidence cannot claim strict point-in-time")
    if evidence.get("out_of_sample_claim") is not False:
        raise ValueError("hot-sector evidence cannot claim out-of-sample validity")
    if evidence.get("temporal_context") != expected_context:
        raise ValueError(
            f"hot-sector evidence.temporal_context must be {expected_context}"
        )
    limitations = evidence.get("limitations")
    required_limitations = {
        "rotation_publisher_receipt_unavailable",
        "candidate_artifact_does_not_establish_out_of_sample_validity",
    }
    if expected_context == "post_observation_generation":
        required_limitations.add("post_observation_reconstruction_not_oos")
    if not isinstance(limitations, list) or not required_limitations.issubset(
        limitations
    ):
        raise ValueError("hot-sector evidence limitations are incomplete")
    deferred = {
        "available": False,
        "reason": "future_data_excluded_from_generation",
        "horizons": {},
    }
    if (
        metadata.get("quality_report") != deferred
        or metadata.get("outcome_report") != deferred
    ):
        raise ValueError("hot-sector generation reports must remain deferred")


def _required_object(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest {field} must be an ISO-8601 timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"manifest {field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"manifest {field} must include an explicit UTC offset")
    return parsed


def _parse_cutoff_date(value: object) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest data_cutoff must be an ISO date or timestamp")
    text = value.strip()
    try:
        return parse_date(text)
    except ValueError:
        return _parse_timestamp(text, "data_cutoff").date()


def _classify_manifest(
    data_cutoff: date | None,
    contract: InputContract,
    metadata: dict[str, object],
) -> tuple[PointInTimeAssurance, tuple[str, ...]]:
    if contract == "generic_json_manifest":
        return (
            "unverified",
            ("unrecognized_candidate_contract",),
        )
    if data_cutoff is None:
        return (
            "unverified",
            ("data_cutoff_unavailable",),
        )
    evidence = _required_object(metadata, "evidence")
    raw_limitations = evidence.get("limitations")
    limitations = (
        tuple(str(item) for item in raw_limitations if isinstance(item, str))
        if isinstance(raw_limitations, list)
        else ()
    )
    return (
        "signal_date_only",
        limitations or ("publisher_receipt_unavailable",),
    )


def _validate_row_dates(rows: list[dict[str, object]], as_of: date) -> date | None:
    discovered: set[date] = set()
    for row in rows:
        for key in ("trade_date", "date", "as_of"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                discovered.add(parse_date(value))
                break
    if len(discovered) > 1:
        values = ", ".join(sorted(value.isoformat() for value in discovered))
        raise ValueError(f"candidate rows contain multiple observation dates: {values}")
    observation_date = next(iter(discovered), None)
    if observation_date is not None and observation_date > as_of:
        raise ValueError("candidate observation date is after selection --as-of")
    return observation_date


def _normalize_rows(rows: list[dict[str, object]], market: Market) -> list[Candidate]:
    normalized: list[Candidate] = []
    for index, row in enumerate(rows, 1):
        symbol = _required_alias(
            row, ("ts_code", "symbol") if market == "CN" else ("ticker", "symbol")
        )
        name = _required_alias(
            row, ("name",) if market == "CN" else ("company_name", "name")
        )
        score_raw = row.get("score")
        if not _is_coercible_finite_number(score_raw):
            score_raw = row.get("relevance")
        if isinstance(score_raw, bool):
            raise ValueError(f"candidate row {index} score must be numeric")
        try:
            score = float(cast(str | int | float, score_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"candidate row {index} score must be numeric") from exc
        if not math.isfinite(score):
            raise ValueError(f"candidate row {index} score must be finite")
        topic = _topic_for_row(row, market)
        if len(name.strip()) > 200:
            raise ValueError(f"candidate row {index} name is too long")
        if len(topic) > 500:
            raise ValueError(f"candidate row {index} topic is too long")
        normalized.append(
            Candidate(
                symbol=validate_symbol(symbol, market),
                name=name.strip(),
                topic=topic,
                score=score,
                features=_safe_features(row),
            )
        )
    return normalized


def _is_coercible_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(cast(str | int | float, value)))
    except (TypeError, ValueError):
        return False


def _required_alias(row: dict[str, object], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = row.get(alias)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError(f"candidate row is missing required field: {'/'.join(aliases)}")


def _topic_for_row(row: dict[str, object], market: Market) -> str:
    keys = (
        ("source_topics", "source_concepts", "topic")
        if market == "CN"
        else (
            "sector",
            "industry",
            "topic",
        )
    )
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            if any(not isinstance(item, str) for item in value):
                raise ValueError(f"candidate {key} must contain only strings")
            clean = [item.strip() for item in value if item.strip()]
            if clean:
                return " / ".join(clean)
        elif isinstance(value, str) and value.strip():
            if value.strip().startswith("["):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    try:
                        parsed = ast.literal_eval(value)
                    except (SyntaxError, ValueError) as exc:
                        raise ValueError(
                            f"candidate {key} is not a valid string list"
                        ) from exc
                if not isinstance(parsed, list) or any(
                    not isinstance(item, str) for item in parsed
                ):
                    raise ValueError(f"candidate {key} must be a string list")
                return (
                    " / ".join(item.strip() for item in parsed if item.strip())
                    or "未分类"
                )
            return value.strip()
    return "未分类"


_PROMPT_FEATURES = {
    "amount_ratio_20d",
    "close_to_20d_high",
    "confidence_label",
    "daily_confirm_score",
    "industry",
    "liquidity_score",
    "relevance",
    "ret_10d",
    "ret_5d",
    "risk_score",
    "score",
    "sector",
    "source_concepts",
    "source_topics",
    "trend_score",
    "volume_score",
}

_PROMPT_FEATURE_ALIASES = {
    "risk_score": "intraday_stability_score",
}


def _safe_features(row: dict[str, object]) -> dict[str, object]:
    features: dict[str, object] = {}
    for key in sorted(_PROMPT_FEATURES):
        value = row.get(key)
        if value is None:
            continue
        output_key = _PROMPT_FEATURE_ALIASES.get(key, key)
        if isinstance(value, str):
            features[output_key] = value[:500]
        elif isinstance(value, bool | int | float):
            features[output_key] = value
        elif isinstance(value, list):
            features[output_key] = [str(item)[:100] for item in value[:20]]
    return features


__all__ = [
    "Candidate",
    "CandidateUniverse",
    "HOT_SECTOR_INPUT_CONTRACTS",
    "SOURCE_CONCEPTS_POLICY_SHA256",
    "is_hot_sector_contract",
    "load_candidate_universe",
    "parse_date",
]
