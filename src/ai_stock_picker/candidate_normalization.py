"""Normalize supported candidate contracts into a common model-facing shape."""

from __future__ import annotations

import math
from typing import cast

from .candidate_models import Candidate, ValidatedManifest
from .contracts import validate_symbol

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


def normalize_candidates(manifest: ValidatedManifest) -> tuple[Candidate, ...]:
    """Normalize and validate all candidate rows."""

    candidates = tuple(
        _normalize_row(row, manifest, index)
        for index, row in enumerate(manifest.rows, 1)
    )
    symbols = [candidate.symbol for candidate in candidates]
    if len(symbols) != len(set(symbols)):
        duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
        raise ValueError(f"candidate symbols must be unique: {duplicates}")
    return candidates


def _normalize_row(
    row: dict[str, object], manifest: ValidatedManifest, index: int
) -> Candidate:
    if manifest.contract == "stock_candidate_universe_v1":
        symbol = _required_string(row, "symbol", index)
        name = _required_string(row, "name", index)
        topic = _optional_topic(row.get("topic"))
        features = _generic_features(row.get("features"), index)
    else:
        symbol = _required_string(row, "ts_code", index)
        name = _required_string(row, "name", index)
        topic = _hot_topic(row)
        features = _allowlisted_features(row)
    score = _finite_score(row.get("score"), index)
    if len(name) > 200:
        raise ValueError(f"candidate row {index} name is too long")
    if len(topic) > 500:
        raise ValueError(f"candidate row {index} topic is too long")
    return Candidate(
        symbol=validate_symbol(symbol, manifest.market),
        name=name,
        topic=topic,
        score=score,
        features=features,
    )


def _required_string(row: dict[str, object], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate row {index} is missing required field: {field}")
    return value.strip()


def _finite_score(value: object, index: int) -> float:
    if isinstance(value, bool):
        raise ValueError(f"candidate row {index} score must be numeric")
    try:
        score = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"candidate row {index} score must be numeric") from exc
    if not math.isfinite(score):
        raise ValueError(f"candidate row {index} score must be finite")
    return score


def _optional_topic(value: object) -> str:
    if value is None:
        return "未分类"
    if not isinstance(value, str):
        raise ValueError("candidate topic must be a string")
    return value.strip() or "未分类"


def _generic_features(value: object, index: int) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"candidate row {index} features must be an object")
    return _bounded_features(cast(dict[str, object], value))


def _hot_topic(row: dict[str, object]) -> str:
    topics: list[str] = []
    for field in ("source_topics", "source_concepts"):
        value = row.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(f"candidate {field} must contain only strings")
        strings = cast(list[str], value)
        topics.extend(item.strip() for item in strings if item.strip())
    return " / ".join(dict.fromkeys(topics)) or "未分类"


def _allowlisted_features(row: dict[str, object]) -> dict[str, object]:
    return _bounded_features({key: row[key] for key in _PROMPT_FEATURES if key in row})


def _bounded_features(values: dict[str, object]) -> dict[str, object]:
    features: dict[str, object] = {}
    for key in sorted(values):
        value = values[key]
        if value is None:
            continue
        if isinstance(value, str):
            features[key[:100]] = value[:500]
        elif isinstance(value, bool | int | float):
            features[key[:100]] = value
        elif isinstance(value, list):
            features[key[:100]] = [str(item)[:100] for item in value[:20]]
    return features


__all__ = ["normalize_candidates"]
