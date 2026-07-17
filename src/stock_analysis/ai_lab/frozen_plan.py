"""Append-only, network-free production selection plans."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast

from .alias_contracts import alias_map_bytes, alias_maps_sha256
from .bundle_paths import reject_symlink_path, safe_bundle_path
from .contracts import Market, Style, validate_prompt_profile
from .evidence_consistency import (
    deepseek_inference_kwargs,
    numeric_ranking_bytes,
    provider_parameters,
)
from .providers import ProviderParameterSchema
from .selection import (
    SelectionPlan,
    build_selection_plan,
    read_plan_candidate_snapshot,
)

PICK_PLAN_SCHEMA_VERSION = "1.0.0"
_PLAN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def write_pick_plan(
    plan: SelectionPlan,
    output_dir: str | Path,
    *,
    generated_at: datetime | None = None,
    campaign_id: str | None = None,
    trial_id: str | None = None,
) -> Path:
    """Freeze one production prompt and all request parameters without a call."""

    if plan.prompt_profile not in {
        "production_v4",
        "ranking_only_v1",
        "bounded_ranking_v1",
    }:
        raise ValueError("pick-plan requires a current production or research profile")
    if plan.provider_parameter_schema != "explicit_v2":
        raise ValueError("pick-plan requires explicit_v2 provider parameters")
    _validate_optional_id(campaign_id, "campaign_id")
    _validate_optional_id(trial_id, "trial_id")
    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("generated_at must include a UTC offset")
    candidate_name = f"candidate_input{plan.universe.path.suffix.lower()}"
    files = {
        candidate_name: read_plan_candidate_snapshot(plan),
        "numeric_ranking.json": numeric_ranking_bytes(plan),
        "prompt.txt": plan.prompt.encode(),
    }
    alias_files, alias_metadata = _frozen_alias_artifacts(plan)
    files.update(alias_files)
    payload: dict[str, object] = {
        "schema_version": PICK_PLAN_SCHEMA_VERSION,
        "artifact_type": "ai_pick_plan",
        "generated_at": created.astimezone(timezone.utc).isoformat(),
        "campaign_id": campaign_id,
        "trial_id": trial_id,
        "market": plan.market,
        "provider": plan.provider,
        "model": plan.model,
        "provider_parameter_schema": plan.provider_parameter_schema,
        "provider_parameters": provider_parameters(plan),
        "prompt_version": plan.prompt_version,
        "prompt_profile": plan.prompt_profile,
        **plan.ranking_policy_fields,
        "selection_as_of": plan.universe.selection_as_of.isoformat(),
        "style": plan.style,
        "top_n": plan.top_n,
        "candidate_path": candidate_name,
        "source_candidate_path": plan.source_candidate_path,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "presentation_order": list(plan.presentation_order),
        **alias_metadata,
        "alias_maps_sha256": alias_maps_sha256(
            dict(plan.symbol_aliases), dict(plan.name_aliases)
        ),
        "prompt_path": "prompt.txt",
        "prompt_sha256": _digest(plan.prompt.encode()),
        "numeric_ranking_path": "numeric_ranking.json",
        "receipt_path": "receipt.json",
        "api_calls": 0,
        "research_only": True,
    }
    receipt = {
        "schema_version": "1.0.0",
        "artifact_type": "ai_pick_plan_receipt",
        "plan_core_sha256": _digest(_json_bytes(payload)),
    }
    files["receipt.json"] = _json_bytes(receipt)
    payload["files"] = _file_records(files)
    root = _reserve_directory(output_dir)
    for relative, content in files.items():
        _write_exclusive(root / relative, content)
    plan_bytes = _json_bytes(payload)
    _write_exclusive(root / "plan.json", plan_bytes)
    load_pick_plan(root / "plan.json")
    return root


def load_pick_plan(plan_path: str | Path) -> SelectionPlan:
    """Strictly rebuild a frozen production plan from its archived inputs."""

    supplied_path = Path(plan_path).expanduser()
    reject_symlink_path(supplied_path, label="pick plan")
    path = supplied_path.resolve()
    if path.name != "plan.json" or not path.is_file():
        raise ValueError("pick plan path must end in a regular plan.json")
    root = path.parent
    payload = _read_object(path)
    if payload.get("schema_version") != PICK_PLAN_SCHEMA_VERSION:
        raise ValueError("pick plan schema_version is invalid")
    if payload.get("artifact_type") != "ai_pick_plan":
        raise ValueError("pick plan artifact_type is invalid")
    _validate_file_records(root, payload)
    _validate_receipt(root, payload)
    market = _market(payload.get("market"))
    inference = (
        deepseek_inference_kwargs(payload.get("provider_parameters"))
        if market == "CN"
        else None
    )
    symbol_aliases = _load_alias_map(root, payload, "symbol")
    name_aliases = _load_alias_map(root, payload, "name")
    if payload.get("alias_maps_sha256") != alias_maps_sha256(
        symbol_aliases, name_aliases
    ):
        raise ValueError("pick plan alias_maps_sha256 is inconsistent")
    plan = build_selection_plan(
        market=market,
        candidates_path=_indexed_path(root, payload, "candidate_path"),
        as_of=_date(payload, "selection_as_of"),
        top_n=_integer(payload, "top_n"),
        style=_style(payload.get("style")),
        model=_string(payload, "model"),
        provider_parameter_schema=_parameter_schema(
            payload.get("provider_parameter_schema")
        ),
        thinking=inference["thinking"] if inference is not None else None,
        reasoning_effort=(
            inference["reasoning_effort"] if inference is not None else None
        ),
        max_tokens=inference["max_tokens"] if inference is not None else None,
        presentation_order=_string_list(payload, "presentation_order"),
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
        prompt_profile=validate_prompt_profile(_string(payload, "prompt_profile")),
        source_candidate_path=_string(payload, "source_candidate_path"),
        campaign_id=_optional_string(payload, "campaign_id"),
        trial_id=_optional_string(payload, "trial_id"),
        plan_sha256=_digest(path.read_bytes()),
        research_only=_boolean(payload, "research_only"),
    )
    _validate_rebuilt_plan(root, payload, plan)
    return plan


def load_trial_plan(plan_path: str | Path) -> SelectionPlan:
    """Load a production pick plan or an existing legacy stability trial."""

    supplied = Path(plan_path).expanduser()
    reject_symlink_path(supplied, label="trial plan")
    path = supplied.resolve()
    if path.name == "plan.json":
        return load_pick_plan(path)
    from .evidence import load_stability_trial

    return load_stability_trial(path)


def _validate_rebuilt_plan(
    root: Path, payload: Mapping[str, object], plan: SelectionPlan
) -> None:
    expected: dict[str, object] = {
        "provider": plan.provider,
        "provider_parameter_schema": plan.provider_parameter_schema,
        "provider_parameters": provider_parameters(plan),
        "prompt_version": plan.prompt_version,
        "prompt_profile": plan.prompt_profile,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "api_calls": 0,
        "source_candidate_path": plan.source_candidate_path,
        "campaign_id": plan.campaign_id,
        "trial_id": plan.trial_id,
        "research_only": plan.research_only,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"pick plan {field} is inconsistent")
    if payload.get("ranking_policy") != plan.ranking_policy_record:
        raise ValueError("pick plan ranking_policy is inconsistent")
    if plan.ranking_policy is None and "ranking_policy" in payload:
        raise ValueError("unbounded pick plan must not declare a ranking policy")
    prompt = _indexed_path(root, payload, "prompt_path").read_bytes()
    if prompt != plan.prompt.encode() or payload.get("prompt_sha256") != _digest(
        prompt
    ):
        raise ValueError("pick plan prompt is inconsistent")
    ranking = _indexed_path(root, payload, "numeric_ranking_path")
    if ranking.read_bytes() != numeric_ranking_bytes(plan):
        raise ValueError("pick plan numeric ranking is inconsistent")


def _frozen_alias_artifacts(
    plan: SelectionPlan,
) -> tuple[dict[str, bytes], dict[str, object]]:
    symbols = dict(plan.symbol_aliases)
    names = dict(plan.name_aliases)
    if bool(symbols) != bool(names):
        raise ValueError("opaque pick plans require both symbol and name aliases")
    metadata: dict[str, object] = {
        "symbol_aliases": symbols,
        "name_aliases": names,
        "symbol_aliases_path": None,
        "name_aliases_path": None,
        "symbol_aliases_sha256": None,
        "name_aliases_sha256": None,
    }
    if not symbols:
        return {}, metadata
    symbol_bytes = alias_map_bytes(symbols)
    name_bytes = alias_map_bytes(names)
    metadata.update(
        {
            "symbol_aliases_path": "symbol_aliases.json",
            "name_aliases_path": "name_aliases.json",
            "symbol_aliases_sha256": _digest(symbol_bytes),
            "name_aliases_sha256": _digest(name_bytes),
        }
    )
    return {
        "symbol_aliases.json": symbol_bytes,
        "name_aliases.json": name_bytes,
    }, metadata


def _load_alias_map(
    root: Path,
    payload: Mapping[str, object],
    kind: str,
) -> dict[str, str]:
    field = f"{kind}_aliases"
    aliases = _string_map(payload, field)
    path_field = f"{field}_path"
    hash_field = f"{field}_sha256"
    if not aliases:
        if payload.get(path_field) is not None or payload.get(hash_field) is not None:
            raise ValueError(f"pick plan empty {field} has frozen file metadata")
        return aliases
    path = _indexed_path(root, payload, path_field)
    content = path.read_bytes()
    if payload.get(hash_field) != _digest(content):
        raise ValueError(f"pick plan {field} hash is inconsistent")
    raw = _read_object(path)
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw.items()
    ):
        raise ValueError(f"pick plan {field} file must contain a string map")
    archived = cast(dict[str, str], raw)
    if content != alias_map_bytes(archived) or archived != aliases:
        raise ValueError(f"pick plan {field} file is inconsistent")
    return aliases


def _validate_file_records(root: Path, payload: Mapping[str, object]) -> None:
    records = payload.get("files")
    if not isinstance(records, dict):
        raise ValueError("pick plan files index is invalid")
    expected = {"plan.json"}
    for relative, record in records.items():
        if not isinstance(relative, str) or not isinstance(record, dict):
            raise ValueError("pick plan file record is invalid")
        path = _inside(root, relative)
        content = path.read_bytes()
        if record != {"sha256": _digest(content), "bytes": len(content)}:
            raise ValueError(f"pick plan file hash mismatch: {relative}")
        expected.add(relative)
    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if actual != expected:
        raise ValueError("pick plan directory contains unindexed files")


def _validate_receipt(root: Path, payload: Mapping[str, object]) -> None:
    receipt = _read_object(_indexed_path(root, payload, "receipt_path"))
    core = dict(payload)
    core.pop("files", None)
    expected = {
        "schema_version": "1.0.0",
        "artifact_type": "ai_pick_plan_receipt",
        "plan_core_sha256": _digest(_json_bytes(core)),
    }
    if receipt != expected:
        raise ValueError("pick plan receipt does not match plan.json")


def _reserve_directory(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing overwrite of frozen pick plan: {root}"
        ) from exc
    return root


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pick plan must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("pick plan must contain a JSON object")
    return cast(dict[str, object], value)


def _inside(root: Path, relative: str) -> Path:
    path = safe_bundle_path(root, relative, label="pick plan")
    if not path.is_file():
        raise ValueError("pick plan contains an unsafe file path")
    return path


def _indexed_path(root: Path, payload: Mapping[str, object], field: str) -> Path:
    relative = _string(payload, field)
    records = payload.get("files")
    if not isinstance(records, dict) or relative not in records:
        raise ValueError(f"pick plan {field} is missing from the files index")
    return _inside(root, relative)


def _market(value: object) -> Market:
    if value not in {"CN", "US"}:
        raise ValueError("pick plan market is invalid")
    return cast(Market, value)


def _style(value: object) -> Style:
    if value not in {"momentum", "quality", "growth"}:
        raise ValueError("pick plan style is invalid")
    return cast(Style, value)


def _parameter_schema(value: object) -> ProviderParameterSchema:
    if value != "explicit_v2":
        raise ValueError("pick plan provider_parameter_schema is invalid")
    return "explicit_v2"


def _string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"pick plan {field} must be a non-empty string")
    return value


def _optional_string(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"pick plan {field} must be null or a non-empty string")
    return value


def _boolean(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"pick plan {field} must be a boolean")
    return value


def _integer(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"pick plan {field} must be an integer")
    return value


def _date(payload: Mapping[str, object], field: str) -> date:
    value = _string(payload, field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"pick plan {field} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"pick plan {field} must be a canonical ISO date")
    return parsed


def _string_list(payload: Mapping[str, object], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"pick plan {field} must be a string array")
    return cast(list[str], value)


def _string_map(payload: Mapping[str, object], field: str) -> dict[str, str]:
    value = payload.get(field)
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError(f"pick plan {field} must be a string map")
    return cast(dict[str, str], value)


def _file_records(files: Mapping[str, bytes]) -> dict[str, dict[str, object]]:
    return {
        path: {"sha256": _digest(content), "bytes": len(content)}
        for path, content in sorted(files.items())
    }


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _validate_optional_id(value: str | None, field: str) -> None:
    if value is not None and _PLAN_ID.fullmatch(value) is None:
        raise ValueError(f"pick plan {field} contains unsupported characters")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    )


__all__ = [
    "PICK_PLAN_SCHEMA_VERSION",
    "load_pick_plan",
    "load_trial_plan",
    "write_pick_plan",
]
