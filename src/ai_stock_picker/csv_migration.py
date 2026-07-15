"""Explicit migration from exploratory legacy CSV to a versioned manifest."""

from __future__ import annotations

import ast
import csv
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import cast

from .contracts import Market, validate_symbol
from .storage import write_json_document

_MAX_INPUT_BYTES = 10_000_000


def migrate_csv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    market: Market,
    observation_date: date,
    generated_at: datetime,
    data_cutoff: date,
) -> Path:
    """Convert legacy market-specific CSV rows to the common v1 manifest."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must include an explicit UTC offset")
    if data_cutoff > observation_date:
        raise ValueError("data_cutoff must not follow observation_date")
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"CSV input does not exist: {source}")
    raw = source.read_bytes()
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError("CSV input exceeds the 10 MB safety limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV input must be UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("CSV input has no header")
    rows = [
        _normalize_csv_row(dict(row), market, index)
        for index, row in enumerate(reader, 1)
    ]
    if not rows:
        raise ValueError("CSV input contains no candidate rows")
    if len(rows) > 1000:
        raise ValueError("CSV input exceeds the 1000-row candidate limit")
    symbols = [cast(str, row["symbol"]) for row in rows]
    if len(symbols) != len(set(symbols)):
        raise ValueError("CSV candidate symbols must be unique")
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "stock_candidate_universe",
        "market": market,
        "observation_date": observation_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "universe_size": len(rows),
        "candidates": rows,
    }
    return write_json_document(payload, output_path)


def _normalize_csv_row(
    row: dict[str, object], market: Market, index: int
) -> dict[str, object]:
    symbol = _required_alias(
        row,
        ("ts_code", "symbol") if market == "CN" else ("ticker", "symbol"),
        index,
    )
    name = _required_alias(
        row,
        ("name",) if market == "CN" else ("company_name", "name"),
        index,
    )
    score = _score(row.get("score", row.get("relevance")), index)
    topic = _csv_topic(row, market)
    return {
        "symbol": validate_symbol(symbol, market),
        "name": name,
        "score": score,
        "topic": topic,
    }


def _required_alias(
    row: dict[str, object], aliases: tuple[str, ...], index: int
) -> str:
    for alias in aliases:
        value = row.get(alias)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"CSV row {index} is missing required field: {'/'.join(aliases)}")


def _score(value: object, index: int) -> float:
    if isinstance(value, bool):
        raise ValueError(f"CSV row {index} score must be numeric")
    try:
        score = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CSV row {index} score must be numeric") from exc
    if not math.isfinite(score):
        raise ValueError(f"CSV row {index} score must be finite")
    return score


def _csv_topic(row: dict[str, object], market: Market) -> str:
    keys = (
        ("source_topics", "source_concepts", "topic")
        if market == "CN"
        else ("sector", "industry", "topic")
    )
    values: list[str] = []
    for key in keys:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        parsed = _parse_string_list(value)
        if parsed is not None:
            values.extend(parsed)
        else:
            values.append(value.strip())
    return " / ".join(dict.fromkeys(item for item in values if item)) or "未分类"


def _parse_string_list(value: str) -> list[str] | None:
    text = value.strip()
    if not text.startswith("["):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError) as exc:
            raise ValueError("CSV topic field is not a valid string list") from exc
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise ValueError("CSV topic field must be a string list")
    return [item.strip() for item in parsed if item.strip()]


__all__ = ["migrate_csv"]
