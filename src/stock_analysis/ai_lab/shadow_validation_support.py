"""Low-level structural helpers for offline shadow validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

from .bundle_paths import reject_symlink_path, safe_bundle_path
from .contracts import (
    LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_TOMBSTONE_REASONS,
)

_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def validate_model_identity(manifest: Mapping[str, object]) -> None:
    provider = manifest.get("provider")
    parameters = manifest.get("model_parameters")
    if provider not in {"deepseek", "openai"} or not isinstance(parameters, dict):
        raise ValueError("shadow model identity is invalid")
    if set(parameters) != {
        "provider",
        "model",
        "max_output_tokens",
        "thinking",
        "reasoning_effort",
    }:
        raise ValueError("shadow model parameters are invalid")
    model = parameters.get("model")
    if (
        parameters.get("provider") != provider
        or not isinstance(model, str)
        or _MODEL.fullmatch(model) is None
        or manifest.get("model_partition") != f"{provider}--{model}"
    ):
        raise ValueError("shadow model partition is inconsistent")
    maximum = parameters.get("max_output_tokens")
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not 1 <= maximum <= 65_536
    ):
        raise ValueError("shadow max_output_tokens is invalid")
    thinking = parameters.get("thinking")
    effort = parameters.get("reasoning_effort")
    if provider == "openai" and (thinking is not None or effort is not None):
        raise ValueError("OpenAI shadow contains DeepSeek reasoning parameters")
    if provider == "deepseek" and (
        thinking not in {"enabled", "disabled"}
        or (thinking == "enabled" and effort not in {"high", "max"})
        or (thinking == "disabled" and effort is not None)
    ):
        raise ValueError("DeepSeek shadow reasoning parameters are invalid")


def validate_campaign_pins(
    records: list[tuple[dict[str, object], dict[str, object]]],
) -> None:
    model_pins: dict[str, tuple[object, ...]] = {}
    date_pins: dict[str, tuple[object, ...]] = {}
    for summary, manifest in records:
        model_partition = cast(str, summary["model_partition"])
        model_key = f"{summary['arm']}/{model_partition}"
        model_pin = (
            manifest.get("provider"),
            manifest.get("model_parameters"),
            manifest.get("prompt_profile"),
            manifest.get("prompt_version"),
            manifest.get("style"),
            manifest.get("top_n"),
            manifest.get("input_contract"),
        )
        previous_model = model_pins.setdefault(model_key, model_pin)
        if previous_model != model_pin:
            raise ValueError("shadow model partition parameters drifted across dates")
        signal_date = cast(str, summary["signal_date"])
        if manifest.get("schema_version") == LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION:
            date_pin = (
                manifest.get("plan_sha256"),
                manifest.get("input_contract"),
                manifest.get("input_sha256"),
                manifest.get("candidate_symbols_sha256"),
                manifest.get("prompt_sha256"),
                manifest.get("ranking_policy"),
            )
        else:
            date_pin = (
                manifest.get("input_contract"),
                manifest.get("input_sha256"),
                manifest.get("candidate_symbols_sha256"),
            )
        previous_date = date_pins.setdefault(signal_date, date_pin)
        if previous_date != date_pin:
            raise ValueError("shadow models did not use the same frozen daily input")


def campaign_day_roots(root: Path) -> list[Path]:
    """Resolve either the legacy model/date or current arm/model/date layout."""

    children = sorted(root.iterdir())
    if not children:
        return []
    has_arm_layout = all(
        child.name in {"bounded_ranking", "risk_veto"} for child in children
    )
    model_roots: list[Path] = []
    if has_arm_layout:
        for arm_root in children:
            if not arm_root.is_dir() or arm_root.is_symlink():
                raise ValueError("shadow campaign arm partition is invalid")
            model_roots.extend(sorted(arm_root.iterdir()))
    else:
        model_roots = children
    days: list[Path] = []
    for model_root in model_roots:
        if not model_root.is_dir() or model_root.is_symlink():
            raise ValueError("shadow campaign model partition is invalid")
        days.extend(sorted(model_root.iterdir()))
    return days


def date_value(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"shadow {field} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"shadow {field} is not canonical")
    return parsed


def datetime_value(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"shadow {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"shadow {field} must include a UTC offset")
    return parsed


def validated_bundle_root(root: str | Path, label: str) -> Path:
    path = Path(root).expanduser()
    reject_symlink_path(path, label=label)
    path = path.resolve()
    if not path.is_dir() or not (path / "manifest.json").is_file():
        raise ValueError(f"{label} must contain manifest.json")
    return path


def validate_files(root: Path, manifest: Mapping[str, object]) -> None:
    records = manifest.get("files")
    if not isinstance(records, dict):
        raise ValueError("shadow bundle files index is invalid")
    expected = {"manifest.json"}
    for relative, record in records.items():
        if not isinstance(relative, str) or not isinstance(record, dict):
            raise ValueError("shadow bundle file record is invalid")
        path = safe_bundle_path(root, relative, label="shadow bundle")
        reject_symlink_path(path, label="shadow bundle file")
        if not path.is_file():
            raise ValueError("shadow bundle indexed file is missing")
        content = path.read_bytes()
        if record != {"sha256": digest(content), "bytes": len(content)}:
            raise ValueError(f"shadow bundle file hash mismatch: {relative}")
        expected.add(relative)
    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if actual != expected:
        raise ValueError("shadow bundle contains unindexed files")


def indexed_file(root: Path, manifest: Mapping[str, object], field: str) -> Path:
    relative = manifest.get(field)
    records = manifest.get("files")
    if not isinstance(relative, str) or not isinstance(records, dict):
        raise ValueError(f"shadow bundle {field} is invalid")
    if relative not in records:
        raise ValueError(f"shadow bundle {field} is not indexed")
    path = safe_bundle_path(root, relative, label="shadow bundle")
    if not path.is_file():
        raise ValueError(f"shadow bundle {field} is missing")
    return path


def read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("shadow artifact must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("shadow artifact must contain a JSON object")
    return cast(dict[str, object], value)


def digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def validate_tombstone_reason(value: object) -> None:
    if value not in SHADOW_TOMBSTONE_REASONS:
        raise ValueError("shadow tombstone reason is invalid")


__all__ = [
    "campaign_day_roots",
    "date_value",
    "datetime_value",
    "digest",
    "indexed_file",
    "read_object",
    "validate_campaign_pins",
    "validate_files",
    "validate_model_identity",
    "validate_tombstone_reason",
    "validated_bundle_root",
]
