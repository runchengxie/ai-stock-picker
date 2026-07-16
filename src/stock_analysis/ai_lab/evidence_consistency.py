"""Cross-file consistency checks for archived AI selection evidence."""

from __future__ import annotations

import json
import math
import urllib.parse
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast

from .contracts import Market, SelectionArtifact, Style
from .providers import ProviderExchange
from .selection import (
    PromptProfile,
    SelectionPlan,
    build_selection_plan,
    create_selection,
)

EVIDENCE_SCHEMA_VERSION = "1.0.0"

_REJECTION_REASONS = frozenset(
    {
        "selection_validation_failed",
        "provider_response_invalid_json",
        "provider_response_not_object",
        "provider_response_schema_invalid",
    }
)


def validate_complete_artifact(
    plan: SelectionPlan,
    response_text: str,
    artifact: SelectionArtifact,
    *,
    source_candidate_path: str | None = None,
) -> None:
    """Recreate a selection and require every persisted field to agree."""

    expected = create_selection(
        plan,
        response_text,
        generated_at=artifact.generated_at,
    ).model_dump()
    expected_lineage = cast(dict[str, object], expected["lineage"])
    if source_candidate_path is not None:
        expected_lineage["candidate_path"] = source_candidate_path
    if artifact.model_dump() != expected:
        raise ValueError("selection artifact does not match its archived inputs")


def validate_rejection(exchange: ProviderExchange, rejection: str) -> None:
    """Require the rejection reason to match the archived response state."""

    if rejection not in _REJECTION_REASONS:
        raise ValueError("selection rejection reason is invalid")
    if exchange.response_text is None:
        if rejection != exchange.extraction_error:
            raise ValueError("rejection must match the response extraction failure")
    elif rejection != "selection_validation_failed":
        raise ValueError("extracted responses may only fail selection validation")


def validate_selection_evidence(output_dir: str | Path) -> dict[str, object]:
    """Fail closed unless a selection evidence directory is internally consistent."""

    root, manifest = validated_bundle(output_dir, "ai_selection_evidence")
    status = manifest.get("status")
    if status not in {"complete", "rejected"}:
        raise ValueError("evidence status is invalid")
    plan = _archived_selection_plan(root, manifest)
    _validate_selection_manifest(manifest, plan)
    exchange = _archived_exchange(root, manifest)
    validate_exchange(plan, exchange, require_response_text=status == "complete")
    _validate_selection_file_set(root, manifest, exchange, status=cast(str, status))
    expected_response_sha = (
        digest(exchange.response_text.encode())
        if exchange.response_text is not None
        else None
    )
    if manifest.get("response_sha256") != expected_response_sha:
        raise ValueError("evidence response hash does not match model_response.txt")
    selection_path = manifest.get("selection_path")
    if status == "complete":
        if selection_path != "selection.json":
            raise ValueError("complete evidence must reference selection.json")
        artifact = SelectionArtifact.model_validate_json(
            (root / "selection.json").read_text(encoding="utf-8"), strict=True
        )
        if exchange.response_text is None:
            raise ValueError("complete evidence is missing the model response")
        validate_complete_artifact(
            plan,
            exchange.response_text,
            artifact,
            source_candidate_path=_manifest_string(manifest, "source_candidate_path"),
        )
        if manifest.get("rejection") is not None:
            raise ValueError("complete evidence cannot contain a rejection")
    else:
        rejection = manifest.get("rejection")
        if selection_path is not None or not isinstance(rejection, str):
            raise ValueError("rejected evidence has inconsistent status fields")
        validate_rejection(exchange, rejection)
    return manifest


def _archived_selection_plan(
    root: Path, manifest: Mapping[str, object]
) -> SelectionPlan:
    market_value = _manifest_string(manifest, "market")
    if market_value not in {"CN", "US"}:
        raise ValueError("evidence market is invalid")
    style_value = _manifest_string(manifest, "style")
    if style_value not in {"momentum", "quality", "growth"}:
        raise ValueError("evidence style is invalid")
    profile_value = _manifest_string(manifest, "prompt_profile")
    if profile_value not in {"production_v4", "legacy_stability_v3"}:
        raise ValueError("evidence prompt profile is invalid")
    candidate_path = inside(root, _manifest_string(manifest, "candidate_path"))
    selection_as_of = _manifest_date(manifest, "selection_as_of")
    plan = build_selection_plan(
        market=cast(Market, market_value),
        candidates_path=candidate_path,
        as_of=selection_as_of,
        top_n=_strict_int(manifest.get("top_n"), "top_n"),
        style=cast(Style, style_value),
        model=_manifest_string(manifest, "model"),
        presentation_order=_manifest_string_list(manifest, "presentation_order"),
        symbol_aliases=_manifest_string_map(manifest, "symbol_aliases"),
        name_aliases=_manifest_string_map(manifest, "name_aliases"),
        prompt_profile=cast(PromptProfile, profile_value),
    )
    if plan.prompt.encode() != (root / "prompt.txt").read_bytes():
        raise ValueError("archived prompt does not match the candidate snapshot")
    if (root / "numeric_ranking.json").read_bytes() != numeric_ranking_bytes(plan):
        raise ValueError("numeric ranking does not match the candidate snapshot")
    return plan


def _validate_selection_manifest(
    manifest: Mapping[str, object], plan: SelectionPlan
) -> None:
    if manifest.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("evidence schema_version is invalid")
    expected: dict[str, object] = {
        "market": plan.market,
        "provider": plan.provider,
        "model": plan.model,
        "requested_model_alias": plan.model,
        "provider_parameters": provider_parameters(plan.provider),
        "prompt_version": plan.prompt_version,
        "prompt_profile": plan.prompt_profile,
        "style": plan.style,
        "top_n": plan.top_n,
        "selection_as_of": plan.universe.selection_as_of.isoformat(),
        "candidate_available_at": candidate_available_at(plan),
        "input_contract": plan.universe.input_contract,
        "input_count": len(plan.universe.candidates),
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "prompt_sha256": digest(plan.prompt.encode()),
        "api_calls": 1,
        "eligible_as_oos_evidence": False,
        "research_only": plan.prompt_profile != "production_v4",
    }
    for field, expected_value in expected.items():
        if manifest.get(field) != expected_value:
            raise ValueError(f"evidence manifest {field} is inconsistent")
    source_path = _manifest_string(manifest, "source_candidate_path")
    if not Path(source_path).is_absolute():
        raise ValueError("source_candidate_path must be absolute")
    generated_at = _manifest_datetime(manifest, "generated_at")
    available_at = _manifest_datetime(manifest, "available_at")
    if generated_at != available_at:
        raise ValueError("evidence generated_at and available_at must match")


def _archived_exchange(root: Path, manifest: Mapping[str, object]) -> ProviderExchange:
    envelope = read_object(root / "http_request_envelope.json")
    if envelope.get("body_path") != "provider_request_body.json":
        raise ValueError("request envelope body_path is invalid")
    request_body = (root / "provider_request_body.json").read_bytes()
    if envelope.get("body_sha256") != digest(request_body):
        raise ValueError("request envelope body hash is invalid")
    raw_headers = envelope.get("headers")
    if not isinstance(raw_headers, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_headers.items()
    ):
        raise ValueError("request envelope headers are invalid")
    raw_timeout = envelope.get("timeout_seconds")
    if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int | float):
        raise ValueError("request envelope timeout is invalid")
    records = manifest.get("files")
    if not isinstance(records, dict):
        raise ValueError("evidence files index is invalid")
    response_text = (
        (root / "model_response.txt").read_text(encoding="utf-8")
        if "model_response.txt" in records
        else None
    )
    return ProviderExchange(
        provider=_manifest_string(manifest, "provider"),
        model=_manifest_string(manifest, "requested_model_alias"),
        endpoint=_required_string(envelope.get("endpoint"), "request endpoint"),
        request_method=_required_string(envelope.get("method"), "request method"),
        request_headers=tuple(cast(dict[str, str], raw_headers).items()),
        request_body=request_body,
        response_body=(root / "provider_response_body.bin").read_bytes(),
        response_text=response_text,
        actual_model=_optional_manifest_string(manifest, "response_model"),
        extraction_error=_optional_manifest_string(
            manifest, "response_extraction_error"
        ),
        timeout_seconds=float(raw_timeout),
    )


def _validate_selection_file_set(
    root: Path,
    manifest: Mapping[str, object],
    exchange: ProviderExchange,
    *,
    status: str,
) -> None:
    records = cast(dict[str, object], manifest["files"])
    expected = {
        _manifest_string(manifest, "candidate_path"),
        "numeric_ranking.json",
        "prompt.txt",
        "http_request_envelope.json",
        "provider_request_body.json",
        "provider_response_body.bin",
    }
    if exchange.response_text is not None:
        expected.add("model_response.txt")
    if status == "complete":
        expected.add("selection.json")
    if set(records) != expected:
        raise ValueError("evidence bundle has an invalid file set")
    for relative in expected:
        if not inside(root, relative).is_file():
            raise ValueError(f"evidence file is missing: {relative}")


def numeric_ranking_bytes(plan: SelectionPlan) -> bytes:
    """Serialize the deterministic numeric baseline bound to a selection plan."""

    input_positions = {
        candidate.symbol: index
        for index, candidate in enumerate(plan.universe.candidates, start=1)
    }
    hot_sector = plan.universe.input_contract == "hot_sector_candidate_universe_v1"
    relevance_by_symbol = (
        {
            candidate.symbol: _hot_sector_relevance(candidate.features)
            for candidate in plan.universe.candidates
        }
        if hot_sector
        else {}
    )
    if hot_sector:
        ranked = sorted(
            plan.universe.candidates,
            key=lambda candidate: (
                -relevance_by_symbol[candidate.symbol],
                -candidate.score,
                candidate.symbol,
            ),
        )
    else:
        ranked = sorted(
            plan.universe.candidates,
            key=lambda candidate: (-candidate.score, candidate.symbol),
        )
    payload = {
        "ranking_method": (
            "relevance_desc_score_desc_symbol_asc"
            if hot_sector
            else "score_desc_symbol_asc"
        ),
        "input_count": len(ranked),
        "rows": [
            {
                "numeric_rank": rank,
                "input_position": input_positions[candidate.symbol],
                "symbol": candidate.symbol,
                "name": candidate.name,
                "topic": candidate.topic,
                "score": candidate.score,
                "features": candidate.features,
                **(
                    {"relevance": relevance_by_symbol[candidate.symbol]}
                    if hot_sector
                    else {}
                ),
            }
            for rank, candidate in enumerate(ranked, start=1)
        ],
    }
    return _json_bytes(payload)


def _hot_sector_relevance(features: Mapping[str, object]) -> float:
    value = features.get("relevance")
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise ValueError("hot-sector numeric ranking requires finite relevance")
    return float(value)


def provider_parameters(provider: str) -> dict[str, object]:
    """Return the provider parameters committed by the evidence contract."""

    if provider == "deepseek":
        return {"temperature": 0.2, "response_format": {"type": "json_object"}}
    return {"temperature": 0.2, "response_mime_type": "application/json"}


def validate_exchange(
    plan: SelectionPlan,
    exchange: ProviderExchange,
    *,
    require_response_text: bool,
) -> None:
    """Require an exchange to agree with the plan and its raw response bytes."""

    if exchange.provider != plan.provider or exchange.model != plan.model:
        raise ValueError("provider exchange does not match the selection plan")
    if exchange.request_method != "POST":
        raise ValueError("provider exchange request method is invalid")
    if exchange.endpoint != _provider_endpoint(plan.provider, plan.model):
        raise ValueError("provider exchange endpoint does not match the selection plan")
    if not math.isfinite(exchange.timeout_seconds) or exchange.timeout_seconds <= 0:
        raise ValueError("provider exchange timeout must be positive and finite")
    expected_headers = (
        {"Content-Type": "application/json", "Authorization": "<redacted>"}
        if plan.provider == "deepseek"
        else {"Content-Type": "application/json", "x-goog-api-key": "<redacted>"}
    )
    if dict(exchange.request_headers) != expected_headers:
        raise ValueError("provider exchange headers are inconsistent")
    try:
        request = json.loads(exchange.request_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider exchange request must contain JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("provider exchange request body must be an object")
    typed_request = cast(dict[str, object], request)
    _validate_request_prompt(plan, typed_request)
    _validate_request_parameters(plan, typed_request)
    response_text, actual_model, extraction_error = _extract_provider_response(
        plan.provider, exchange.response_body
    )
    if response_text != exchange.response_text:
        raise ValueError("extracted model response does not match provider response")
    if actual_model != exchange.actual_model:
        raise ValueError("response model does not match provider response")
    if extraction_error != exchange.extraction_error:
        raise ValueError("response extraction status does not match provider response")
    if require_response_text and exchange.response_text is None:
        raise ValueError("provider exchange has no extracted model response")
    if exchange.response_text is None:
        if exchange.extraction_error not in _REJECTION_REASONS:
            raise ValueError("provider exchange extraction error is invalid")
    elif exchange.extraction_error is not None:
        raise ValueError("provider exchange has contradictory response status")


def _provider_endpoint(provider: str, model: str) -> str:
    if provider == "deepseek":
        return "https://api.deepseek.com/v1/chat/completions"
    encoded_model = urllib.parse.quote(model, safe="")
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{encoded_model}:generateContent"
    )


def _validate_request_parameters(
    plan: SelectionPlan, request: Mapping[str, object]
) -> None:
    if plan.provider == "deepseek":
        expected = {
            "model": plan.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        actual = {field: request.get(field) for field in expected}
    else:
        expected = {
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            }
        }
        actual = {"generationConfig": request.get("generationConfig")}
    if actual != expected:
        raise ValueError("provider request parameters do not match the selection plan")


def _validate_request_prompt(
    plan: SelectionPlan, request: Mapping[str, object]
) -> None:
    if plan.provider == "deepseek":
        messages = request.get("messages")
        if not isinstance(messages, list):
            raise ValueError("provider request does not contain the exact prompt")
        user_prompts = [
            message.get("content")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        ]
    else:
        contents = request.get("contents")
        if not isinstance(contents, list):
            raise ValueError("provider request does not contain the exact prompt")
        user_prompts = []
        for content in contents:
            if not isinstance(content, dict) or content.get("role") != "user":
                continue
            parts = content.get("parts")
            if isinstance(parts, list):
                user_prompts.extend(
                    part.get("text") for part in parts if isinstance(part, dict)
                )
    if user_prompts != [plan.prompt]:
        raise ValueError("provider request does not contain the exact prompt")


def _extract_provider_response(
    provider: str, payload: bytes
) -> tuple[str | None, str | None, str | None]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, "provider_response_invalid_json"
    if not isinstance(decoded, dict):
        return None, None, "provider_response_not_object"
    body = cast(dict[str, object], decoded)
    actual_model_field = "model" if provider == "deepseek" else "modelVersion"
    raw_model = body.get(actual_model_field)
    actual_model = (
        raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
    )
    try:
        response_text = _provider_response_text(provider, body)
    except (IndexError, TypeError, ValueError):
        return None, actual_model, "provider_response_schema_invalid"
    return response_text, actual_model, None


def _provider_response_text(provider: str, body: Mapping[str, object]) -> str:
    outer_field = "choices" if provider == "deepseek" else "candidates"
    outer = body.get(outer_field)
    if not isinstance(outer, list) or not outer or not isinstance(outer[0], dict):
        raise TypeError(outer_field)
    first = cast(dict[str, object], outer[0])
    if provider == "deepseek":
        message = first.get("message")
        if not isinstance(message, dict):
            raise TypeError("message")
        raw_text = cast(dict[str, object], message).get("content")
    else:
        content = first.get("content")
        if not isinstance(content, dict):
            raise TypeError("content")
        parts = cast(dict[str, object], content).get("parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
            raise TypeError("parts")
        raw_text = cast(dict[str, object], parts[0]).get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("provider response text")
    return raw_text


def candidate_available_at(plan: SelectionPlan) -> str | None:
    """Return the canonical UTC availability time for the candidate snapshot."""

    value = plan.universe.source_generated_at
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def validated_bundle(
    output_dir: str | Path, expected_type: str
) -> tuple[Path, dict[str, object]]:
    """Verify the exact indexed file set and byte digests in one bundle."""

    root = Path(output_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("evidence manifest is missing or unsafe")
    manifest = read_object(manifest_path)
    if manifest.get("artifact_type") != expected_type:
        raise ValueError("evidence artifact_type is invalid")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, dict):
        raise ValueError("evidence files index is invalid")
    expected_paths = {"manifest.json"}
    for relative, raw_record in raw_files.items():
        if not isinstance(relative, str) or not isinstance(raw_record, dict):
            raise ValueError("evidence file record is invalid")
        path = inside(root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"evidence file is missing or unsafe: {relative}")
        payload = path.read_bytes()
        if raw_record != {"sha256": digest(payload), "bytes": len(payload)}:
            raise ValueError(f"evidence file hash mismatch: {relative}")
        expected_paths.add(relative)
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_paths != expected_paths:
        raise ValueError("evidence directory contains unindexed files")
    return root, manifest


def inside(root: Path, relative: str) -> Path:
    """Resolve one bundle-relative path without allowing traversal."""

    if not relative or Path(relative).is_absolute():
        raise ValueError("evidence paths must be non-empty and relative")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes its campaign directory")
    return candidate


def read_object(path: Path) -> dict[str, object]:
    """Load one strict JSON object from an evidence path."""

    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return cast(dict[str, object], value)


def digest(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest for exact bytes."""

    return sha256(payload).hexdigest()


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _manifest_string(manifest: Mapping[str, object], field: str) -> str:
    return _required_string(manifest.get(field), f"evidence {field}")


def _optional_manifest_string(manifest: Mapping[str, object], field: str) -> str | None:
    if field not in manifest:
        raise ValueError(f"evidence {field} is missing")
    value = manifest[field]
    if value is None:
        return None
    return _required_string(value, f"evidence {field}")


def _manifest_string_list(manifest: Mapping[str, object], field: str) -> list[str]:
    value = manifest.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"evidence {field} must be a string array")
    return cast(list[str], value)


def _manifest_string_map(manifest: Mapping[str, object], field: str) -> dict[str, str]:
    value = manifest.get(field)
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError(f"evidence {field} must be a string map")
    return cast(dict[str, str], value)


def _manifest_date(manifest: Mapping[str, object], field: str) -> date:
    value = _manifest_string(manifest, field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"evidence {field} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"evidence {field} must be a canonical ISO date")
    return parsed


def _manifest_datetime(manifest: Mapping[str, object], field: str) -> datetime:
    value = _manifest_string(manifest, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"evidence {field} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"evidence {field} must use UTC")
    return parsed


def _strict_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"evidence {field} must be an integer")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "candidate_available_at",
    "digest",
    "inside",
    "numeric_ranking_bytes",
    "provider_parameters",
    "read_object",
    "validate_complete_artifact",
    "validate_exchange",
    "validate_rejection",
    "validate_selection_evidence",
    "validated_bundle",
]
