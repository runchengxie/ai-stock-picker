"""Validation for the canonical hot-sector candidate contract."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Literal, TypeGuard, cast
from zoneinfo import ZoneInfo

from .time_utils import parse_date


def validate_hot_sector_manifest(
    metadata: dict[str, object],
    rows: tuple[dict[str, object], ...],
    observation_date: date,
    generated_at: datetime,
) -> tuple[tuple[str, ...], Literal["next_trading_session"]]:
    """Validate the complete hot-sector v1 contract."""

    if not isinstance(metadata.get("candidate_universe"), list):
        raise ValueError("hot-sector candidate_universe must be an array")
    expected_date, temporal_context = _validate_temporal_metadata(
        metadata, observation_date, generated_at
    )
    _validate_payload(metadata, rows)
    _validate_provenance(metadata, expected_date)
    limitations = _validate_evidence(metadata, temporal_context)
    return limitations, "next_trading_session"


def _validate_temporal_metadata(
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
    context: Literal[
        "same_day_eod_generation", "post_observation_generation"
    ] = (
        "same_day_eod_generation"
        if generated_local.date() == observation_date
        else "post_observation_generation"
    )
    return expected_date, context


def _validate_payload(
    metadata: dict[str, object], rows: tuple[dict[str, object], ...]
) -> None:
    topics = metadata.get("topics")
    if not isinstance(topics, list):
        raise ValueError("hot-sector topics must be an array")
    for topic in topics:
        _validate_topic(topic)
    for field in ("data_sources", "config_snapshot"):
        if not isinstance(metadata.get(field), dict):
            raise ValueError(f"hot-sector {field} must be an object")
    for row in rows:
        _validate_candidate_row(row)


def _validate_topic(value: object) -> None:
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


def _validate_candidate_row(row: dict[str, object]) -> None:
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


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(float(value))
    )


def _require_nonempty_string_array(value: object, field: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"hot-sector {field} must be a non-empty string array")


def _validate_provenance(metadata: dict[str, object], expected_date: str) -> None:
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
    level = rotation.get("provenance_level")
    if level not in {"signal_date_only", "unavailable"}:
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
    signal_value = rotation.get("signal_date")
    signal_date: date | None = None
    if signal_value is not None:
        try:
            signal_date = parse_date(str(signal_value))
        except ValueError as exc:
            raise ValueError(
                "hot-sector rotation.signal_date must be a valid date or null"
            ) from exc
        if signal_date > as_of_date:
            raise ValueError(
                "hot-sector rotation.signal_date must not exceed as_of_date"
            )
    if level == "signal_date_only" and signal_date is None:
        raise ValueError("hot-sector signal_date_only rotation requires signal_date")
    if level == "unavailable" and signal_value is not None:
        raise ValueError("hot-sector unavailable rotation requires a null signal_date")


def _validate_evidence(
    metadata: dict[str, object],
    expected_context: Literal["same_day_eod_generation", "post_observation_generation"],
) -> tuple[str, ...]:
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
    required = {
        "rotation_publisher_receipt_unavailable",
        "candidate_artifact_does_not_establish_out_of_sample_validity",
    }
    if expected_context == "post_observation_generation":
        required.add("post_observation_reconstruction_not_oos")
    if not isinstance(limitations, list) or not required.issubset(limitations):
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
    return tuple(str(item) for item in limitations if isinstance(item, str))


def _required_object(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


__all__ = ["validate_hot_sector_manifest"]
