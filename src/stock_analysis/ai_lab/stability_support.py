"""Opaque-arm identity mapping and validation for stability campaigns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast

from .prompting import validate_identity_redaction
from .selection import SelectionPlan


def opaque_aliases(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    seed: int,
) -> tuple[dict[str, str], dict[str, str], tuple[dict[str, object], ...]]:
    """Create deterministic aliases ordered by preregistered identity hashes."""

    experiment_date = plan.universe.selection_as_of.isoformat()
    candidates = {candidate.symbol: candidate for candidate in plan.universe.candidates}
    rows: list[tuple[str, str]] = []
    for symbol in candidates:
        material = _identity_material(campaign_id, experiment_date, symbol, seed)
        rows.append((_digest(material), symbol))
    rows.sort()
    symbols: dict[str, str] = {}
    names: dict[str, str] = {}
    mapping: list[dict[str, object]] = []
    for index, (identity_hash, symbol) in enumerate(rows, start=1):
        symbol_alias = f"C{index:03d}"
        name_alias = f"候选{index:03d}"
        candidate = candidates[symbol]
        symbols[symbol] = symbol_alias
        names[symbol] = name_alias
        mapping.append(
            {
                "identity_sha256": identity_hash,
                "symbol": symbol,
                "name": candidate.name,
                "symbol_alias": symbol_alias,
                "name_alias": name_alias,
            }
        )
    return symbols, names, tuple(mapping)


def validate_opaque_trial(root: Path, trial: Mapping[str, object]) -> None:
    """Verify identity removal, reversible mapping, and numeric-field preservation."""

    prompt_path = _inside(root, str(trial.get("prompt_path") or ""))
    try:
        prompt = json.loads(prompt_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("opaque trial prompt must be JSON") from exc
    if not isinstance(prompt, dict):
        raise ValueError("opaque trial prompt must be an object")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    mapping = _identity_mapping(trial.get("identity_mapping"))
    campaign_id = str(trial.get("campaign_id") or "")
    experiment_date = str(trial.get("selection_as_of") or "")
    seed = _strict_int(trial.get("seed"), "seed")
    symbol_aliases: dict[str, str] = {}
    name_aliases: dict[str, str] = {}
    for item in mapping:
        symbol, name, symbol_alias, name_alias = _mapping_identities(item)
        material = _identity_material(campaign_id, experiment_date, symbol, seed)
        if item.get("identity_sha256") != _digest(material):
            raise ValueError("opaque trial identity hash mismatch")
        symbol_aliases[symbol] = symbol_alias
        name_aliases[symbol] = name_alias
    if trial.get("symbol_aliases") != symbol_aliases:
        raise ValueError("opaque trial symbol aliases disagree with its mapping")
    if trial.get("name_aliases") != name_aliases:
        raise ValueError("opaque trial name aliases disagree with its mapping")
    validate_identity_redaction(
        prompt_text,
        (
            (_mapping_identities(item)[0], _mapping_identities(item)[1])
            for item in mapping
        ),
    )
    _validate_numeric_fields(root, prompt, symbol_aliases)


def _identity_mapping(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("opaque trial identity mapping is missing")
    mapping: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("opaque trial identity mapping is invalid")
        mapping.append(cast(dict[str, object], item))
    return mapping


def _mapping_identities(item: Mapping[str, object]) -> tuple[str, str, str, str]:
    values = (
        item.get("symbol"),
        item.get("name"),
        item.get("symbol_alias"),
        item.get("name_alias"),
    )
    if not all(isinstance(value, str) for value in values):
        raise ValueError("opaque trial identity mapping fields are invalid")
    return cast(tuple[str, str, str, str], values)


def _validate_numeric_fields(
    root: Path,
    prompt: dict[str, object],
    symbol_aliases: Mapping[str, str],
) -> None:
    candidate_rows = prompt.get("candidates")
    if not isinstance(candidate_rows, list):
        raise ValueError("opaque trial candidates are invalid")
    prompt_by_alias = {
        row.get("symbol"): row
        for row in candidate_rows
        if isinstance(row, dict) and isinstance(row.get("symbol"), str)
    }
    ranking = _read_object(root / "numeric_ranking.json")
    ranking_rows = ranking.get("rows")
    if not isinstance(ranking_rows, list):
        raise ValueError("numeric ranking rows are invalid")
    numeric_by_symbol = {
        row.get("symbol"): row
        for row in ranking_rows
        if isinstance(row, dict) and isinstance(row.get("symbol"), str)
    }
    for symbol, alias in symbol_aliases.items():
        prompt_row = prompt_by_alias.get(alias)
        numeric_row = numeric_by_symbol.get(symbol)
        if not isinstance(prompt_row, dict) or not isinstance(numeric_row, dict):
            raise ValueError("opaque trial candidate mapping is incomplete")
        if prompt_row.get("score") != numeric_row.get("score") or _numeric_values(
            prompt_row.get("features")
        ) != _numeric_values(numeric_row.get("features")):
            raise ValueError("opaque trial changed a candidate numeric field")


def _numeric_values(value: object, prefix: str = "") -> tuple[tuple[str, float], ...]:
    rows: list[tuple[str, float]] = []
    if isinstance(value, bool):
        return ()
    if isinstance(value, int | float):
        return ((prefix, float(value)),)
    if isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_numeric_values(item, f"{prefix}[{index}]"))
    elif isinstance(value, dict):
        for key, item in sorted(value.items()):
            rows.extend(_numeric_values(item, f"{prefix}.{key}"))
    return tuple(rows)


def _identity_material(
    campaign_id: str, experiment_date: str, symbol: str, seed: int
) -> bytes:
    return json.dumps(
        [campaign_id, experiment_date, symbol, seed],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("evidence paths must be non-empty and relative")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes its campaign directory")
    return candidate


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return cast(dict[str, object], value)


def _strict_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"trial {field} must be an integer")
    return value


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


__all__ = ["opaque_aliases", "validate_opaque_trial"]
