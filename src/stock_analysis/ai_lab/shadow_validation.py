"""Offline validation for owner-generated shadow campaign artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import cast
from zoneinfo import ZoneInfo

from .bundle_paths import reject_symlink_path, safe_bundle_path
from .contracts import (
    SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_MIN_VALID_REPETITIONS,
    SHADOW_REPETITION_NAMES,
    SHADOW_REPETITIONS,
    SHADOW_TOMBSTONE_REASONS,
    Style,
)
from .evidence_consistency import numeric_ranking_bytes
from .providers import ProviderExchange
from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
)
from .selection import build_selection_plan
from .shadow_exchange_validation import validate_shadow_exchange

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_FILES = {
    "http_request_envelope.json",
    "provider_request_body.json",
    "provider_response_body.bin",
}
_COMMON_IDENTITY_FIELDS = (
    "schema_version",
    "campaign_id",
    "signal_date",
    "provider",
    "model_partition",
    "model_parameters",
    "prompt_profile",
    "prompt_version",
    "prompt_sha256",
    "plan_sha256",
    "style",
    "top_n",
    "candidate_snapshot_path",
    "candidate_observation_date",
    "candidate_generated_at",
    "input_contract",
    "input_sha256",
    "candidate_symbols_sha256",
    "ranking_policy",
    "strict_point_in_time",
    "eligible_as_oos_evidence",
    "research_only",
)


def validate_shadow_repetition(root: str | Path) -> dict[str, object]:
    """Validate one terminal repetition directory and its hash index."""

    path = _validated_bundle_root(root, "shadow repetition")
    manifest = _read_object(path / "manifest.json")
    if manifest.get("schema_version") != SHADOW_CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("shadow repetition schema_version is invalid")
    if manifest.get("artifact_type") != "ai_shadow_repetition":
        raise ValueError("shadow repetition artifact_type is invalid")
    status = manifest.get("status")
    if status not in {"complete", "tombstone"}:
        raise ValueError("shadow repetition status is invalid")
    _validate_files(path, manifest)
    _validate_common_manifest(manifest)
    _validate_repetition_file_set(manifest)
    _validate_owner_evidence(path, manifest)
    ranking_path = manifest.get("ranking_path")
    if status == "complete":
        if (
            manifest.get("ranking_contract") != "passed"
            or ranking_path != "ranking.json"
        ):
            raise ValueError("complete shadow repetition requires a passed ranking")
        read_shadow_ranking(path, manifest)
        if manifest.get("tombstone_reason") is not None:
            raise ValueError(
                "complete shadow repetition cannot have a tombstone reason"
            )
    else:
        _validate_tombstone_reason(manifest.get("tombstone_reason"))
        if ranking_path is not None or manifest.get("ranking_contract") == "passed":
            raise ValueError(
                "shadow repetition tombstone cannot preserve a passed rank"
            )
    return manifest


def validate_shadow_day(day_dir: str | Path) -> dict[str, object]:
    """Fail closed on all repetition and consensus artifacts for one model/date."""

    day = Path(day_dir).expanduser()
    reject_symlink_path(day, label="shadow day")
    day = day.resolve()
    if not day.is_dir():
        raise ValueError("shadow day must be a directory")
    expected = {*SHADOW_REPETITION_NAMES, "consensus"}
    actual = {item.name for item in day.iterdir()}
    if actual != expected:
        raise ValueError(
            "shadow day must contain exactly three repetitions and consensus"
        )
    manifests = [
        validate_shadow_repetition(day / name) for name in SHADOW_REPETITION_NAMES
    ]
    _validate_day_identity(day, manifests)
    consensus_root = _validated_bundle_root(day / "consensus", "shadow consensus")
    consensus = _read_object(consensus_root / "manifest.json")
    _validate_consensus_manifest(consensus_root, consensus, manifests)
    selected_symbols: list[str] | None = None
    if consensus["status"] == "complete":
        payload = _read_object(
            _indexed_file(consensus_root, consensus, "consensus_path")
        )
        selected_symbols = cast(list[str], payload["selected_symbols"])
    numeric_fallback = _numeric_fallback_symbols(consensus)
    return {
        "valid": True,
        "campaign_id": consensus["campaign_id"],
        "model_partition": consensus["model_partition"],
        "signal_date": consensus["signal_date"],
        "input_contract": consensus["input_contract"],
        "input_sha256": consensus["input_sha256"],
        "candidate_symbols_sha256": consensus["candidate_symbols_sha256"],
        "prompt_version": consensus["prompt_version"],
        "plan_sha256": consensus["plan_sha256"],
        "repetition_statuses": [item["status"] for item in manifests],
        "valid_repetitions": consensus["valid_repetitions"],
        "consensus_status": consensus["status"],
        "selected_symbols": selected_symbols,
        "numeric_fallback_symbols": numeric_fallback,
        "effective_symbols": selected_symbols or numeric_fallback,
        "selection_source": (
            "bounded_ranking_consensus"
            if selected_symbols is not None
            else "numeric_fallback"
        ),
        "consensus_path": str(consensus_root / "consensus.json")
        if consensus["status"] == "complete"
        else None,
    }


def _numeric_fallback_symbols(consensus: Mapping[str, object]) -> list[str]:
    policy = consensus.get("ranking_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow ranking_policy is invalid")
    locked = policy.get("locked_prefix_symbols")
    boundary = policy.get("boundary_symbols")
    if not isinstance(locked, list) or not isinstance(boundary, list):
        raise ValueError("shadow ranking_policy partitions are invalid")
    if (
        len(locked) != 7
        or len(boundary) != 8
        or any(not isinstance(item, str) for item in [*locked, *boundary])
    ):
        raise ValueError("shadow ranking_policy partitions are invalid")
    return cast(list[str], [*locked, *boundary[:3]])


def validate_shadow_campaign(campaign_root: str | Path) -> dict[str, object]:
    """Validate every model/date day beneath one campaign partition."""

    root = Path(campaign_root).expanduser()
    reject_symlink_path(root, label="shadow campaign")
    root = root.resolve()
    if not root.is_dir() or _IDENTIFIER.fullmatch(root.name) is None:
        raise ValueError("shadow campaign root is invalid")
    days: list[dict[str, object]] = []
    records: list[tuple[dict[str, object], dict[str, object]]] = []
    for model_root in sorted(root.iterdir()):
        if not model_root.is_dir() or model_root.is_symlink():
            raise ValueError("shadow campaign model partition is invalid")
        for day_root in sorted(model_root.iterdir()):
            summary = validate_shadow_day(day_root)
            days.append(summary)
            records.append(
                (summary, _read_object(day_root / "consensus" / "manifest.json"))
            )
    if not days:
        raise ValueError("shadow campaign contains no model/date partitions")
    if any(item["campaign_id"] != root.name for item in days):
        raise ValueError("shadow campaign path does not match artifact campaign_id")
    _validate_campaign_pins(records)
    return {
        "valid": True,
        "campaign_id": root.name,
        "day_count": len(days),
        "complete_consensus_count": sum(
            item["consensus_status"] == "complete" for item in days
        ),
        "days": days,
    }


def _validate_day_identity(day: Path, manifests: list[dict[str, object]]) -> None:
    first = manifests[0]
    for field in _COMMON_IDENTITY_FIELDS:
        if any(item.get(field) != first.get(field) for item in manifests[1:]):
            raise ValueError(f"shadow repetition {field} differs within one day")
    if first.get("signal_date") != day.name:
        raise ValueError("shadow day path does not match signal_date")
    if first.get("model_partition") != day.parent.name:
        raise ValueError("shadow model path does not match model_partition")
    if first.get("campaign_id") != day.parent.parent.name:
        raise ValueError("shadow campaign path does not match campaign_id")
    if [item.get("repetition") for item in manifests] != [1, 2, 3]:
        raise ValueError("shadow repetition numbers are not canonical")


def _validate_consensus_manifest(
    root: Path,
    consensus: dict[str, object],
    repetitions: list[dict[str, object]],
) -> None:
    if consensus.get("schema_version") != SHADOW_CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("shadow consensus schema_version is invalid")
    if consensus.get("artifact_type") != "ai_shadow_consensus":
        raise ValueError("shadow consensus artifact_type is invalid")
    _validate_files(root, consensus)
    _validate_common_manifest(consensus)
    if consensus.get("repetitions") != SHADOW_REPETITIONS:
        raise ValueError("shadow consensus repetitions is invalid")
    if consensus.get("min_valid_repetitions") != SHADOW_MIN_VALID_REPETITIONS:
        raise ValueError("shadow consensus min_valid_repetitions is invalid")
    for field in _COMMON_IDENTITY_FIELDS:
        if consensus.get(field) != repetitions[0].get(field):
            raise ValueError(f"shadow consensus {field} differs from repetitions")
    valid = [
        index
        for index, manifest in enumerate(repetitions, start=1)
        if manifest["status"] == "complete"
    ]
    if consensus.get("valid_repetitions") != valid:
        raise ValueError("shadow consensus valid_repetitions is inconsistent")
    if len(valid) < SHADOW_MIN_VALID_REPETITIONS:
        if consensus.get("status") != "tombstone":
            raise ValueError("insufficient repetitions require consensus tombstone")
        _validate_tombstone_reason(consensus.get("tombstone_reason"))
        if consensus.get("tombstone_reason") != "insufficient_valid_repetitions":
            raise ValueError("shadow consensus tombstone reason is inconsistent")
        if consensus.get("consensus_path") is not None:
            raise ValueError("consensus tombstone cannot point to a ranking")
        if consensus.get("files") != {}:
            raise ValueError("consensus tombstone cannot contain ranked files")
        return
    if consensus.get("status") != "complete":
        raise ValueError("sufficient repetitions require complete consensus")
    if consensus.get("tombstone_reason") is not None:
        raise ValueError("complete consensus cannot have tombstone reason")
    if set(cast(dict[str, object], consensus["files"])) != {"consensus.json"}:
        raise ValueError("complete consensus file set is invalid")
    consensus_path = _indexed_file(root, consensus, "consensus_path")
    payload = _read_object(consensus_path)
    expected = _consensus_from_archives(root.parent, repetitions)
    if payload != expected:
        raise ValueError("shadow consensus does not match archived repetitions")


def _consensus_from_archives(
    day_root: Path, repetitions: list[dict[str, object]]
) -> dict[str, object]:
    valid = [
        (
            index,
            read_shadow_ranking(
                day_root / SHADOW_REPETITION_NAMES[index - 1], manifest
            ),
        )
        for index, manifest in enumerate(repetitions, start=1)
        if manifest["status"] == "complete"
    ]
    locked = valid[0][1][:7]
    for _index, symbols in valid[1:]:
        if symbols[:7] != locked:
            raise ValueError("shadow repetitions disagree on the locked prefix")
    records = _tally_records(valid)
    winners = [cast(str, item["symbol"]) for item in records[:3]]
    return {
        "schema_version": SHADOW_CAMPAIGN_SCHEMA_VERSION,
        "artifact_type": "ai_shadow_consensus_ranking",
        "method": "votes_then_borda_then_median_then_symbol_v1",
        "valid_repetitions": [item[0] for item in valid],
        "locked_prefix": list(locked),
        "boundary_winners": winners,
        "selected_symbols": [*locked, *winners],
        "boundary_tallies": records,
    }


def _tally_records(
    valid: list[tuple[int, tuple[str, ...]]],
) -> list[dict[str, object]]:
    tallies: dict[str, dict[str, object]] = {}
    for _index, symbols in valid:
        for order, symbol in enumerate(symbols[7:], start=1):
            tally = tallies.setdefault(
                symbol, {"votes": 0, "ranking_points": 0, "orders": []}
            )
            tally["votes"] = cast(int, tally["votes"]) + 1
            tally["ranking_points"] = cast(int, tally["ranking_points"]) + 4 - order
            cast(list[int], tally["orders"]).append(order)
    records: list[dict[str, object]] = [
        {
            "symbol": symbol,
            "votes": cast(int, value["votes"]),
            "ranking_points": cast(int, value["ranking_points"]),
            "median_order": float(median(cast(list[int], value["orders"]))),
        }
        for symbol, value in tallies.items()
    ]
    records.sort(
        key=lambda item: (
            -cast(int, item["votes"]),
            -cast(int, item["ranking_points"]),
            cast(float, item["median_order"]),
            cast(str, item["symbol"]),
        )
    )
    return records


def read_shadow_ranking(root: Path, manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Read one hash-indexed canonical ranking after structural validation."""

    payload = _read_object(_indexed_file(root, manifest, "ranking_path"))
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("shadow ranking schema_version is invalid")
    if payload.get("artifact_type") != "ai_ranking_diagnostic":
        raise ValueError("shadow ranking artifact_type is invalid")
    symbols = payload.get("symbols")
    if (
        not isinstance(symbols, list)
        or len(symbols) != 10
        or any(not isinstance(item, str) or not item for item in symbols)
    ):
        raise ValueError("shadow ranking symbols are invalid")
    if len(symbols) != len(set(symbols)):
        raise ValueError("shadow ranking symbols must be unique")
    result = tuple(cast(list[str], symbols))
    locked, boundary = _policy_partitions(manifest)
    if result[:7] != locked or not set(result[7:]).issubset(boundary):
        raise ValueError("shadow ranking violates the archived bounded policy")
    return result


def _validate_common_manifest(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != SHADOW_CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("shadow schema_version is invalid")
    campaign_id = manifest.get("campaign_id")
    if not isinstance(campaign_id, str) or _IDENTIFIER.fullmatch(campaign_id) is None:
        raise ValueError("shadow campaign_id is invalid")
    signal_date = _date_value(manifest.get("signal_date"), "signal_date")
    generated_at = _datetime_value(manifest.get("generated_at"), "generated_at")
    generated_local = generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if generated_local.date() < signal_date or (
        generated_local.date() == signal_date
        and (generated_local.hour, generated_local.minute) < (16, 0)
    ):
        raise ValueError("shadow generated_at precedes the signal-date close")
    if (
        manifest.get("prompt_profile") != "bounded_ranking_v2"
        or manifest.get("prompt_version") != BOUNDED_RANKING_V2_PROMPT_VERSION
    ):
        raise ValueError("shadow prompt contract is invalid")
    if manifest.get("top_n") != BOUNDED_RANKING_V2_POLICY.required_output_count:
        raise ValueError("shadow top_n is invalid")
    if manifest.get("style") not in {"momentum", "quality"}:
        raise ValueError("shadow style is invalid")
    for field in (
        "prompt_sha256",
        "plan_sha256",
        "input_sha256",
        "candidate_symbols_sha256",
    ):
        value = manifest.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"shadow {field} is invalid")
    if manifest.get("candidate_snapshot_path") not in {
        "candidate_input.json",
        "candidate_input.csv",
    }:
        raise ValueError("shadow candidate_snapshot_path is invalid")
    if (
        manifest.get("strict_point_in_time") is not False
        or manifest.get("eligible_as_oos_evidence") is not False
        or manifest.get("research_only") is not True
    ):
        raise ValueError("shadow research evidence flags are invalid")
    _validate_model_identity(manifest)
    _policy_partitions(manifest)


def _validate_model_identity(manifest: Mapping[str, object]) -> None:
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


def _policy_partitions(
    manifest: Mapping[str, object],
) -> tuple[tuple[str, ...], frozenset[str]]:
    policy = manifest.get("ranking_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow ranking_policy is invalid")
    static = BOUNDED_RANKING_V2_POLICY.contract_record()
    if any(policy.get(field) != value for field, value in static.items()):
        raise ValueError("shadow ranking_policy static contract is invalid")
    expected_keys = {
        *static,
        "numeric_ranking_method",
        "locked_prefix_symbols",
        "boundary_symbols",
    }
    if set(policy) != expected_keys:
        raise ValueError("shadow ranking_policy fields are invalid")
    locked = policy.get("locked_prefix_symbols")
    boundary = policy.get("boundary_symbols")
    if (
        not isinstance(locked, list)
        or len(locked) != BOUNDED_RANKING_V2_POLICY.locked_prefix_count
        or not isinstance(boundary, list)
        or len(boundary)
        != (
            BOUNDED_RANKING_V2_POLICY.boundary_end_rank
            - BOUNDED_RANKING_V2_POLICY.boundary_start_rank
            + 1
        )
        or any(not isinstance(item, str) or not item for item in [*locked, *boundary])
        or len({*locked, *boundary}) != len(locked) + len(boundary)
    ):
        raise ValueError("shadow ranking_policy partitions are invalid")
    return tuple(cast(list[str], locked)), frozenset(cast(list[str], boundary))


def _validate_repetition_file_set(manifest: Mapping[str, object]) -> None:
    records = cast(dict[str, object], manifest["files"])
    names = set(records)
    candidates = {
        name
        for name in names
        if name in {"candidate_input.json", "candidate_input.csv"}
    }
    if len(candidates) != 1:
        raise ValueError("shadow repetition requires one candidate snapshot")
    if candidates != {manifest.get("candidate_snapshot_path")}:
        raise ValueError("shadow candidate snapshot path is inconsistent")
    base = {*candidates, "numeric_ranking.json", "prompt.txt"}
    status = manifest.get("status")
    if status == "complete":
        expected = {*base, *_NETWORK_FILES, "model_response.txt", "ranking.json"}
        if names != expected:
            raise ValueError("complete shadow repetition file set is invalid")
        if (
            manifest.get("transport_contract") != "passed"
            or manifest.get("ranking_contract") != "passed"
            or manifest.get("publication_contract") not in {"passed", "failed"}
        ):
            raise ValueError("complete shadow repetition contracts are inconsistent")
        return
    reason = manifest.get("tombstone_reason")
    if reason in {"provider_call_failed", "watchdog_missing_repetition"}:
        allowed = {frozenset(base)}
        expected_contracts = ("failed", "not_evaluated", "not_evaluated")
    elif reason == "transport_contract_failed":
        allowed = {
            frozenset(base),
            frozenset({*base, *_NETWORK_FILES}),
        }
        expected_contracts = ("failed", "not_evaluated", "not_evaluated")
    elif reason == "ranking_contract_failed":
        allowed = {
            frozenset({*base, *_NETWORK_FILES, "model_response.txt"}),
        }
        expected_contracts = ("passed", "failed", "not_evaluated")
    else:
        raise ValueError("shadow repetition tombstone reason is invalid")
    if frozenset(names) not in allowed:
        raise ValueError("shadow repetition tombstone file set is invalid")
    actual_contracts = (
        manifest.get("transport_contract"),
        manifest.get("ranking_contract"),
        manifest.get("publication_contract"),
    )
    if actual_contracts != expected_contracts:
        raise ValueError("shadow repetition tombstone contracts are inconsistent")


def _validate_owner_evidence(root: Path, manifest: Mapping[str, object]) -> None:
    candidate_name = cast(str, manifest["candidate_snapshot_path"])
    candidate_path = safe_bundle_path(root, candidate_name, label="shadow candidate")
    signal_date = _date_value(manifest.get("signal_date"), "signal_date")
    style = cast(Style, manifest.get("style"))
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidate_path,
        as_of=signal_date,
        top_n=BOUNDED_RANKING_V2_POLICY.required_output_count,
        style=style,
        prompt_profile="bounded_ranking_v2",
    )
    expected = {
        "input_contract": plan.universe.input_contract,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "ranking_policy": plan.ranking_policy_record,
        "candidate_observation_date": (
            plan.universe.observation_date.isoformat()
            if plan.universe.observation_date is not None
            else None
        ),
        "candidate_generated_at": (
            plan.universe.source_generated_at.astimezone(timezone.utc).isoformat()
            if plan.universe.source_generated_at is not None
            else None
        ),
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"shadow {field} differs from the candidate snapshot")
    prompt = (root / "prompt.txt").read_bytes()
    if prompt != plan.prompt.encode() or _digest(prompt) != manifest.get(
        "prompt_sha256"
    ):
        raise ValueError("shadow prompt does not match the candidate snapshot")
    if (root / "numeric_ranking.json").read_bytes() != numeric_ranking_bytes(plan):
        raise ValueError("shadow numeric ranking does not match the candidate snapshot")
    if _NETWORK_FILES.issubset(cast(dict[str, object], manifest["files"])):
        _validate_network_evidence(root, manifest, plan.prompt)
    generated_at = _datetime_value(manifest.get("generated_at"), "generated_at")
    if (
        plan.universe.source_generated_at is not None
        and plan.universe.source_generated_at > generated_at
    ):
        raise ValueError("shadow candidate was generated after the repetition")


def _validate_network_evidence(
    root: Path, manifest: Mapping[str, object], prompt: str
) -> None:
    envelope = _read_object(root / "http_request_envelope.json")
    if set(envelope) != {"endpoint", "method", "headers", "timeout_seconds"}:
        raise ValueError("shadow request envelope fields are invalid")
    headers = envelope.get("headers")
    if not isinstance(headers, dict) or headers != {
        "Content-Type": "application/json",
        "Authorization": "<redacted>",
    }:
        raise ValueError("shadow request envelope headers are invalid")
    timeout = envelope.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError("shadow request envelope timeout is invalid")
    response_path = root / "model_response.txt"
    response_text = (
        response_path.read_text(encoding="utf-8") if response_path.is_file() else None
    )
    parameters = manifest.get("model_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("shadow model_parameters are invalid")
    typed_parameters = cast(dict[str, object], parameters)
    exchange = ProviderExchange(
        provider=cast(str, manifest["provider"]),
        model=cast(str, typed_parameters["model"]),
        endpoint=cast(str, envelope.get("endpoint")),
        request_method=cast(str, envelope.get("method")),
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=(root / "provider_request_body.json").read_bytes(),
        response_body=(root / "provider_response_body.bin").read_bytes(),
        response_text=response_text,
        actual_model=cast(str | None, manifest.get("actual_model")),
        extraction_error=cast(str | None, manifest.get("response_extraction_error")),
        timeout_seconds=float(timeout),
        refusal=cast(str | None, manifest.get("refusal")),
        usage=cast(dict[str, object] | None, manifest.get("usage")),
    )
    validate_shadow_exchange(
        exchange,
        prompt=prompt,
        provider=cast(str, manifest["provider"]),
        model_parameters=typed_parameters,
    )


def _validate_campaign_pins(
    records: list[tuple[dict[str, object], dict[str, object]]],
) -> None:
    model_pins: dict[str, tuple[object, ...]] = {}
    date_pins: dict[str, tuple[object, ...]] = {}
    for summary, manifest in records:
        model_partition = cast(str, summary["model_partition"])
        model_pin = (
            manifest.get("provider"),
            manifest.get("model_parameters"),
            manifest.get("prompt_profile"),
            manifest.get("prompt_version"),
            manifest.get("style"),
            manifest.get("top_n"),
            manifest.get("input_contract"),
        )
        previous_model = model_pins.setdefault(model_partition, model_pin)
        if previous_model != model_pin:
            raise ValueError("shadow model partition parameters drifted across dates")
        signal_date = cast(str, summary["signal_date"])
        date_pin = (
            manifest.get("plan_sha256"),
            manifest.get("input_contract"),
            manifest.get("input_sha256"),
            manifest.get("candidate_symbols_sha256"),
            manifest.get("prompt_sha256"),
            manifest.get("ranking_policy"),
        )
        previous_date = date_pins.setdefault(signal_date, date_pin)
        if previous_date != date_pin:
            raise ValueError("shadow models did not use the same frozen daily input")


def _date_value(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"shadow {field} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"shadow {field} is not canonical")
    return parsed


def _datetime_value(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"shadow {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"shadow {field} must include a UTC offset")
    return parsed


def _validated_bundle_root(root: str | Path, label: str) -> Path:
    path = Path(root).expanduser()
    reject_symlink_path(path, label=label)
    path = path.resolve()
    if not path.is_dir() or not (path / "manifest.json").is_file():
        raise ValueError(f"{label} must contain manifest.json")
    return path


def _validate_files(root: Path, manifest: Mapping[str, object]) -> None:
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
        if record != {"sha256": _digest(content), "bytes": len(content)}:
            raise ValueError(f"shadow bundle file hash mismatch: {relative}")
        expected.add(relative)
    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if actual != expected:
        raise ValueError("shadow bundle contains unindexed files")


def _indexed_file(root: Path, manifest: Mapping[str, object], field: str) -> Path:
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


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("shadow artifact must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("shadow artifact must contain a JSON object")
    return cast(dict[str, object], value)


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _validate_tombstone_reason(value: object) -> None:
    if value not in SHADOW_TOMBSTONE_REASONS:
        raise ValueError("shadow tombstone reason is invalid")


__all__ = [
    "read_shadow_ranking",
    "validate_shadow_campaign",
    "validate_shadow_day",
    "validate_shadow_repetition",
]
