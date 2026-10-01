#!/usr/bin/env python3
"""Validate the pinned public research snapshot before the static-site build."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {
    "schema_version",
    "reviewed_on",
    "research_only",
    "strict_point_in_time",
    "eligible_as_oos_evidence",
    "sources",
    "studies",
    "daily",
}
PRIVATE_FIELDS = {
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "prompt",
    "raw_response",
    "candidate_path",
    "selected_symbols",
    "effective_symbols",
}
DAILY_FIELDS = {
    "date",
    "arm",
    "model",
    "status",
    "valid_repetitions",
    "evidence_status",
    "consensus_sha256",
    "input_sha256",
}


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _check_public(value: Any) -> None:
    if isinstance(value, dict):
        if PRIVATE_FIELDS.intersection(value):
            raise ValueError("private fields cannot enter the public snapshot")
        for child in value.values():
            _check_public(child)
    elif isinstance(value, list):
        for child in value:
            _check_public(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite metric")
    elif isinstance(value, str) and value.startswith(("/home/", "/mnt/")):
        raise ValueError("machine paths cannot enter the public snapshot")


def _validate_shape(value: Any, shape: Any) -> None:
    if isinstance(shape, dict):
        if not isinstance(value, dict) or set(value) != set(shape):
            raise ValueError("nested fields differ from the public contract")
        for key, child in shape.items():
            _validate_shape(value[key], child)
    elif isinstance(shape, list):
        if not isinstance(value, list):
            raise ValueError("nested list differs from the public contract")
        for child in value:
            _validate_shape(child, shape[0] if shape else None)
    elif isinstance(value, dict | list):
        raise ValueError("nested value differs from the public contract")


def _validate_daily(daily: dict[str, Any]) -> None:
    if set(daily) != {"rows", "offline_rehearsal"}:
        raise ValueError("daily fields differ from the public contract")
    seen = set()
    for row in daily["rows"]:
        if row.get("evidence_status") != "prospective_bound":
            raise ValueError("daily results must have prospective launch evidence")
        if set(row) != DAILY_FIELDS:
            raise ValueError("daily fields differ from the public contract")
        date.fromisoformat(row["date"])
        identity = (row["date"], row["arm"], row["model"])
        if identity in seen:
            raise ValueError("duplicate daily result")
        seen.add(identity)
        if row["status"] not in {"complete", "tombstone"}:
            raise ValueError("invalid daily terminal status")
        repetitions = row["valid_repetitions"]
        if type(repetitions) is not int or not 0 <= repetitions <= 3:
            raise ValueError("invalid daily repetition count")
        for key in ("consensus_sha256", "input_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                raise ValueError("invalid daily SHA-256")


def _validate_history(studies: dict[str, Any]) -> None:
    stability = studies.get("stability")
    if stability:
        counts = [
            stability["calls"],
            stability["days"],
            stability["passed"],
            stability["required"],
            *stability["arms"].values(),
        ]
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError("invalid stability counts")
        if (
            sum(stability["arms"].values()) != stability["passed"]
            or stability["calls"] != 5 * stability["days"]
            or stability["required"] > stability["calls"]
            or any(count > stability["days"] for count in stability["arms"].values())
        ):
            raise ValueError("stability counts do not reconcile")
    models = studies.get("models")
    if models:
        if models["return_backtest_executed"] is not False:
            raise ValueError("the model return backtest was not run")
        total = 0
        for model in models["models"].values():
            total += model["calls"]
            if (
                not 0
                <= model["publication_passes"]
                <= model["ranking_passes"]
                <= model["calls"]
            ):
                raise ValueError("model counts do not reconcile")
        if total != models["calls"]:
            raise ValueError("model counts do not reconcile")


def validate_snapshot(data: dict[str, Any]) -> None:
    if set(data) != FIELDS:
        raise ValueError("snapshot fields differ from the public contract")
    if data["schema_version"] != "research_site.v1":
        raise ValueError("unsupported research snapshot")
    if (
        data["research_only"] is not True
        or data["strict_point_in_time"] is not False
        or data["eligible_as_oos_evidence"] is not False
    ):
        raise ValueError("public evidence cannot upgrade research status")
    date.fromisoformat(data["reviewed_on"])
    _check_public(data)
    ids = set()
    for source in data["sources"]:
        if set(source) != {"id", "file", "sha256"}:
            raise ValueError("source fields differ from the public contract")
        if source["id"] in ids or Path(source["file"]).name != source["file"]:
            raise ValueError("invalid source identity")
        ids.add(source["id"])
        if not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            raise ValueError("invalid source SHA-256")
    allowed = {"stability", "models", "guarded", "numeric", "turnover"}
    if set(data["studies"]) - allowed:
        raise ValueError("unreviewed study identity")
    shapes = json.loads((ROOT / "site/research-contract.json").read_text())
    for identity, study in data["studies"].items():
        _validate_shape(study, shapes["studies"][identity])
        if not study["source_ids"] or not set(study["source_ids"]) <= ids:
            raise ValueError("study has no matching source")
    rehearsal = data["daily"]["offline_rehearsal"]
    if rehearsal is not None:
        _validate_shape(rehearsal, shapes["offline_rehearsal"])
    _validate_history(data["studies"])
    _validate_daily(data["daily"])


def read_snapshot(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("research snapshot SHA-256 mismatch")
    data = json.loads(raw, object_pairs_hook=_object_pairs)
    validate_snapshot(data)
    return data
