"""Append-only evidence bundles and deterministic stability-trial plans."""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from .alias_contracts import alias_maps_sha256
from .contracts import Market, SelectionArtifact, Style
from .evidence_consistency import (
    EVIDENCE_SCHEMA_VERSION,
    LEGACY_EVIDENCE_SCHEMA_VERSION,
    validate_selection_evidence,
)
from .evidence_consistency import (
    candidate_available_at as _candidate_available_at,
)
from .evidence_consistency import (
    deepseek_inference_kwargs as _deepseek_inference_kwargs,
)
from .evidence_consistency import (
    inside as _inside,
)
from .evidence_consistency import (
    numeric_ranking_bytes as _numeric_ranking_bytes,
)
from .evidence_consistency import (
    provider_parameters as _provider_parameters,
)
from .evidence_consistency import (
    read_object as _read_object,
)
from .evidence_consistency import (
    validate_complete_artifact as _validate_complete_artifact,
)
from .evidence_consistency import (
    validate_exchange as _validate_exchange,
)
from .evidence_consistency import (
    validate_rejection as _validate_rejection,
)
from .evidence_consistency import (
    validated_bundle as _validated_bundle,
)
from .evidence_contracts import selection_contracts as _selection_contracts
from .providers import ProviderExchange, ProviderParameterSchema
from .selection import (
    LEGACY_STABILITY_PROMPT_VERSION,
    SelectionPlan,
    build_selection_plan,
    read_plan_candidate_snapshot,
)
from .stability_support import (
    opaque_aliases as _opaque_aliases,
)
from .stability_support import (
    validate_opaque_trial as _validate_opaque_trial,
)

LEGACY_STABILITY_SCHEMA_VERSION = "1.0.0"
STABILITY_SCHEMA_VERSION = "2.0.0"
DEFAULT_SHUFFLE_SEEDS = (101, 202, 303)
DEFAULT_OPAQUE_SEED = 404
_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def write_selection_evidence(
    plan: SelectionPlan,
    exchange: ProviderExchange,
    artifact: SelectionArtifact,
    output_dir: str | Path,
) -> Path:
    """Write one complete provider exchange and validated selection once."""

    _validate_exchange(plan, exchange, require_response_text=True)
    if exchange.response_text is None:
        raise ValueError("complete evidence requires an extracted model response")
    if artifact.lineage.prompt_sha256 != _digest(plan.prompt.encode()):
        raise ValueError("selection prompt hash does not match the exact prompt")
    if artifact.lineage.response_sha256 != _digest(exchange.response_text.encode()):
        raise ValueError("selection response hash does not match the model response")
    _validate_complete_artifact(plan, exchange.response_text, artifact)
    contracts, diagnostic = _selection_contracts(
        plan,
        exchange,
        generated_at=artifact.generated_at,
    )
    if contracts["publication_contract"] != "passed" or diagnostic is not None:
        raise ValueError("complete evidence failed independent publication validation")
    files = _exchange_files(plan, exchange)
    files["selection.json"] = artifact.model_dump_json(indent=2).encode("utf-8") + b"\n"
    manifest = _selection_manifest(
        plan,
        exchange,
        files,
        status="complete",
        available_at=artifact.generated_at,
        selection_path="selection.json",
        rejection=None,
        contracts=contracts,
    )
    return _write_bundle(output_dir, files, manifest)


def write_rejected_selection_evidence(
    plan: SelectionPlan,
    exchange: ProviderExchange,
    output_dir: str | Path,
    *,
    generated_at: datetime | None = None,
    rejection: str | None = None,
) -> Path:
    """Archive a provider response that failed selection validation."""

    _validate_exchange(plan, exchange, require_response_text=False)
    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("generated_at must include a UTC offset")
    reason = rejection or exchange.extraction_error or "selection_validation_failed"
    _validate_rejection(exchange, reason)
    files = _exchange_files(plan, exchange)
    contracts, diagnostic = _selection_contracts(
        plan,
        exchange,
        generated_at=created.astimezone(timezone.utc),
    )
    if contracts["publication_contract"] == "passed":
        raise ValueError("valid publication response cannot be archived as rejected")
    if diagnostic is not None:
        files["ranking_diagnostic.json"] = diagnostic
    manifest = _selection_manifest(
        plan,
        exchange,
        files,
        status="rejected",
        available_at=created.astimezone(timezone.utc),
        selection_path=None,
        rejection=reason,
        contracts=contracts,
    )
    return _write_bundle(output_dir, files, manifest)


def write_stability_campaign(
    base_plan: SelectionPlan,
    output_dir: str | Path,
    *,
    campaign_id: str,
    shuffle_seeds: Sequence[int] = DEFAULT_SHUFFLE_SEEDS,
    opaque_seed: int = DEFAULT_OPAQUE_SEED,
    generated_at: datetime | None = None,
) -> Path:
    """Freeze the preregistered five-arm legacy-prompt campaign without a call."""

    if len(base_plan.universe.candidates) < 3:
        raise ValueError("stability campaign requires at least three candidates")
    campaign = campaign_id.strip()
    if _CAMPAIGN_ID.fullmatch(campaign) is None:
        raise ValueError("campaign_id contains unsupported characters")
    seeds = _shuffle_seeds(shuffle_seeds)
    if isinstance(opaque_seed, bool) or not isinstance(opaque_seed, int):
        raise ValueError("opaque_seed must be an integer")
    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("generated_at must include a UTC offset")
    candidate_payload = read_plan_candidate_snapshot(base_plan)
    candidate_name = f"candidate_input{base_plan.universe.path.suffix.lower()}"
    files: dict[str, bytes] = {
        candidate_name: candidate_payload,
        "numeric_ranking.json": _numeric_ranking_bytes(base_plan),
    }
    variants = _stability_variants(
        base_plan,
        campaign_id=campaign,
        candidate_name=candidate_name,
        seeds=seeds,
        opaque_seed=opaque_seed,
        files=files,
    )
    manifest: dict[str, object] = {
        "schema_version": STABILITY_SCHEMA_VERSION,
        "artifact_type": "ai_stability_campaign",
        "status": "planned",
        "generated_at": created.astimezone(timezone.utc).isoformat(),
        "available_at": None,
        "campaign_id": campaign,
        "candidate_available_at": _candidate_available_at(base_plan),
        "market": base_plan.market,
        "provider": base_plan.provider,
        "model": base_plan.model,
        "prompt_version": LEGACY_STABILITY_PROMPT_VERSION,
        "prompt_profile": "legacy_stability_v3",
        "style": base_plan.style,
        "top_n": base_plan.top_n,
        "shuffle_seeds": list(seeds),
        "opaque_seed": opaque_seed,
        "api_calls": 0,
        "eligible_as_oos_evidence": False,
        "variants": variants,
        "files": _file_records(files),
    }
    root = _reserve_directory(output_dir)
    _write_files(root, files)
    _write_exclusive(root / "manifest.json", _json_bytes(manifest))
    validate_stability_campaign(root)
    return root


def _stability_variants(
    base_plan: SelectionPlan,
    *,
    campaign_id: str,
    candidate_name: str,
    seeds: tuple[int, int, int],
    opaque_seed: int,
    files: dict[str, bytes],
) -> list[dict[str, object]]:
    canonical_order = base_plan.presentation_order
    variants = [
        _stability_variant(
            base_plan,
            campaign_id=campaign_id,
            trial_id="canonical",
            order=canonical_order,
            symbol_aliases={},
            name_aliases={},
            identity_mapping=(),
            candidate_name=candidate_name,
            seed=None,
            files=files,
        )
    ]
    for seed, order in zip(seeds, _fixed_shuffles(canonical_order, seeds), strict=True):
        variants.append(
            _stability_variant(
                base_plan,
                campaign_id=campaign_id,
                trial_id=f"shuffle_{seed}",
                order=order,
                symbol_aliases={},
                name_aliases={},
                identity_mapping=(),
                candidate_name=candidate_name,
                seed=seed,
                files=files,
            )
        )
    symbols, names, mapping = _opaque_aliases(
        base_plan,
        campaign_id=campaign_id,
        seed=opaque_seed,
    )
    variants.append(
        _stability_variant(
            base_plan,
            campaign_id=campaign_id,
            trial_id=f"opaque_{opaque_seed}",
            order=canonical_order,
            symbol_aliases=symbols,
            name_aliases=names,
            identity_mapping=mapping,
            candidate_name=candidate_name,
            seed=opaque_seed,
            files=files,
        )
    )
    return variants


def load_stability_trial(trial_path: str | Path) -> SelectionPlan:
    """Rebuild one frozen trial and require byte-identical prompt material."""

    path = Path(trial_path).expanduser().resolve()
    if path.name != "trial.json" or len(path.parents) < 3:
        raise ValueError("trial plan path must end in trial.json")
    campaign_root = path.parents[2]
    validate_stability_campaign(campaign_root)
    trial = _read_object(path)
    if trial.get("artifact_type") != "ai_stability_trial":
        raise ValueError("trial artifact_type is invalid")
    candidate_path = _inside(campaign_root, str(trial.get("candidate_path") or ""))
    prompt_path = _inside(campaign_root, str(trial.get("prompt_path") or ""))
    if _digest(candidate_path.read_bytes()) != trial.get("input_sha256"):
        raise ValueError("trial candidate hash mismatch")
    presentation = _string_list(trial.get("presentation_order"), "presentation_order")
    raw_aliases = trial.get("symbol_aliases")
    if not isinstance(raw_aliases, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_aliases.items()
    ):
        raise ValueError("trial symbol_aliases must be a string map")
    raw_name_aliases = trial.get("name_aliases")
    if not isinstance(raw_name_aliases, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_name_aliases.items()
    ):
        raise ValueError("trial name_aliases must be a string map")
    market = cast(Market, trial.get("market"))
    style = cast(Style, trial.get("style"))
    trial_schema = str(trial.get("schema_version") or "")
    if trial_schema not in {
        LEGACY_STABILITY_SCHEMA_VERSION,
        STABILITY_SCHEMA_VERSION,
    }:
        raise ValueError("trial schema_version is invalid")
    inference = (
        _deepseek_inference_kwargs(trial.get("provider_parameters"))
        if market == "CN"
        and trial_schema == STABILITY_SCHEMA_VERSION
        and trial.get("provider_parameter_schema", "explicit_v2") == "explicit_v2"
        else None
    )
    parameter_schema = (
        "legacy_v1"
        if trial_schema == LEGACY_STABILITY_SCHEMA_VERSION
        else str(trial.get("provider_parameter_schema", "explicit_v2"))
    )
    if parameter_schema not in {"legacy_v1", "explicit_v2"}:
        raise ValueError("trial provider_parameter_schema is invalid")
    plan = build_selection_plan(
        market=market,
        candidates_path=candidate_path,
        as_of=datetime.fromisoformat(str(trial.get("selection_as_of"))).date(),
        top_n=_strict_int(trial.get("top_n"), "top_n"),
        style=style,
        model=str(trial.get("model") or ""),
        provider_parameter_schema=cast(ProviderParameterSchema, parameter_schema),
        thinking=inference["thinking"] if inference is not None else None,
        reasoning_effort=(
            inference["reasoning_effort"] if inference is not None else None
        ),
        max_tokens=inference["max_tokens"] if inference is not None else None,
        presentation_order=presentation,
        symbol_aliases=cast(dict[str, str], raw_aliases),
        name_aliases=cast(dict[str, str], raw_name_aliases),
        prompt_profile="legacy_stability_v3",
        source_candidate_path=str(trial.get("source_candidate_path") or candidate_path),
        campaign_id=str(trial.get("campaign_id") or "") or None,
        trial_id=str(trial.get("trial_id") or "") or None,
        plan_sha256=_digest(path.read_bytes()),
        research_only=True,
    )
    expected_prompt = prompt_path.read_bytes()
    if plan.prompt.encode() != expected_prompt:
        raise ValueError("rebuilt prompt differs from the frozen trial prompt")
    if _digest(expected_prompt) != trial.get("prompt_sha256"):
        raise ValueError("trial prompt hash mismatch")
    if (
        plan.provider != trial.get("provider")
        or plan.prompt_version != trial.get("prompt_version")
        or trial.get("prompt_profile") != "legacy_stability_v3"
    ):
        raise ValueError("trial runtime identity is incompatible")
    expected_parameters = _provider_parameters(
        plan,
        evidence_schema_version=(
            EVIDENCE_SCHEMA_VERSION
            if trial_schema == STABILITY_SCHEMA_VERSION
            else LEGACY_EVIDENCE_SCHEMA_VERSION
        ),
    )
    if trial.get("provider_parameters") != expected_parameters:
        raise ValueError("trial provider parameters are incompatible")
    return plan


def validate_stability_campaign(output_dir: str | Path) -> dict[str, object]:
    """Fail closed unless the frozen preregistered five-arm campaign is unchanged."""

    root, manifest = _validated_bundle(output_dir, "ai_stability_campaign")
    campaign_schema = str(manifest.get("schema_version") or "")
    if campaign_schema not in {
        LEGACY_STABILITY_SCHEMA_VERSION,
        STABILITY_SCHEMA_VERSION,
    }:
        raise ValueError("stability campaign schema_version is invalid")
    if manifest.get("status") != "planned" or manifest.get("api_calls") != 0:
        raise ValueError("stability campaign status is invalid")
    variants = manifest.get("variants")
    if not isinstance(variants, list) or len(variants) != 5:
        raise ValueError("stability campaign must contain five variants")
    campaign_id = manifest.get("campaign_id")
    if not isinstance(campaign_id, str) or _CAMPAIGN_ID.fullmatch(campaign_id) is None:
        raise ValueError("stability campaign_id is invalid")
    seeds = _shuffle_seeds(
        _integer_list(manifest.get("shuffle_seeds"), "shuffle_seeds")
    )
    opaque_seed = _strict_int(manifest.get("opaque_seed"), "opaque_seed")
    expected_ids = [
        "canonical",
        *(f"shuffle_{seed}" for seed in seeds),
        f"opaque_{opaque_seed}",
    ]
    expected_seed_by_id: dict[str, int | None] = {
        "canonical": None,
        **{f"shuffle_{seed}": seed for seed in seeds},
        f"opaque_{opaque_seed}": opaque_seed,
    }
    observed_ids, orders = _validate_campaign_variants(
        root,
        variants,
        campaign_id=campaign_id,
        expected_seed_by_id=expected_seed_by_id,
        campaign_schema=campaign_schema,
    )
    if observed_ids != expected_ids:
        raise ValueError("stability campaign arm identities are invalid")
    canonical = orders["canonical"]
    canonical_trial = _read_object(root / "trials/canonical/trial.json")
    canonical_candidate_path = _inside(
        root, str(canonical_trial.get("candidate_path") or "")
    )
    canonical_inference = (
        _deepseek_inference_kwargs(canonical_trial.get("provider_parameters"))
        if canonical_trial.get("market") == "CN"
        and campaign_schema == STABILITY_SCHEMA_VERSION
        and canonical_trial.get("provider_parameter_schema", "explicit_v2")
        == "explicit_v2"
        else None
    )
    canonical_parameter_schema = (
        "legacy_v1"
        if campaign_schema == LEGACY_STABILITY_SCHEMA_VERSION
        else str(canonical_trial.get("provider_parameter_schema", "explicit_v2"))
    )
    canonical_plan = build_selection_plan(
        market=cast(Market, canonical_trial.get("market")),
        candidates_path=canonical_candidate_path,
        as_of=datetime.fromisoformat(
            str(canonical_trial.get("selection_as_of"))
        ).date(),
        top_n=_strict_int(canonical_trial.get("top_n"), "top_n"),
        style=cast(Style, canonical_trial.get("style")),
        model=str(canonical_trial.get("model") or ""),
        provider_parameter_schema=cast(
            ProviderParameterSchema, canonical_parameter_schema
        ),
        thinking=(
            canonical_inference["thinking"] if canonical_inference is not None else None
        ),
        reasoning_effort=(
            canonical_inference["reasoning_effort"]
            if canonical_inference is not None
            else None
        ),
        max_tokens=(
            canonical_inference["max_tokens"]
            if canonical_inference is not None
            else None
        ),
        prompt_profile="legacy_stability_v3",
    )
    if canonical != canonical_plan.presentation_order:
        raise ValueError("canonical arm does not use the standard rendering order")
    shuffle_orders = [orders[f"shuffle_{seed}"] for seed in seeds]
    if tuple(shuffle_orders) != _fixed_shuffles(canonical, seeds):
        raise ValueError("stability shuffle arms do not match their fixed seeds")
    if orders[f"opaque_{opaque_seed}"] != canonical:
        raise ValueError("opaque arm must preserve canonical presentation order")
    opaque_trial = _read_object(root / f"trials/opaque_{opaque_seed}/trial.json")
    _validate_opaque_trial(root, opaque_trial)
    return manifest


def _validate_campaign_variants(
    root: Path,
    variants: Sequence[object],
    *,
    campaign_id: str,
    expected_seed_by_id: Mapping[str, int | None],
    campaign_schema: str,
) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    observed_ids: list[str] = []
    orders: dict[str, tuple[str, ...]] = {}
    for raw_variant in variants:
        if not isinstance(raw_variant, dict):
            raise ValueError("stability variant must be an object")
        variant = cast(dict[str, object], raw_variant)
        trial_path = _inside(root, str(variant.get("trial_path") or ""))
        if trial_path.name != "trial.json":
            raise ValueError("stability trial path is invalid")
        trial = _read_object(trial_path)
        if trial.get("schema_version") != campaign_schema:
            raise ValueError("stability trial schema_version mismatch")
        trial_id = trial.get("trial_id")
        if not isinstance(trial_id, str):
            raise ValueError("stability trial_id is invalid")
        observed_ids.append(trial_id)
        if trial.get("campaign_id") != campaign_id:
            raise ValueError("stability trial campaign_id mismatch")
        if trial.get("prompt_version") != LEGACY_STABILITY_PROMPT_VERSION:
            raise ValueError("stability trial prompt version mismatch")
        if trial.get("prompt_profile") != "legacy_stability_v3":
            raise ValueError("stability trial prompt profile mismatch")
        if trial_id not in expected_seed_by_id:
            raise ValueError("stability trial identity is invalid")
        if trial.get("seed") != expected_seed_by_id[trial_id]:
            raise ValueError("stability trial seed mismatch")
        order = tuple(
            _string_list(trial.get("presentation_order"), "presentation_order")
        )
        orders[trial_id] = order
        if variant.get("trial_id") != trial_id:
            raise ValueError("stability variant identity mismatch")
    return observed_ids, orders


def _stability_variant(
    base_plan: SelectionPlan,
    *,
    campaign_id: str,
    trial_id: str,
    order: tuple[str, ...],
    symbol_aliases: Mapping[str, str],
    name_aliases: Mapping[str, str],
    identity_mapping: Sequence[Mapping[str, object]],
    candidate_name: str,
    seed: int | None,
    files: dict[str, bytes],
) -> dict[str, object]:
    plan = build_selection_plan(
        market=base_plan.market,
        candidates_path=base_plan.universe.path,
        as_of=base_plan.universe.selection_as_of,
        top_n=base_plan.top_n,
        style=base_plan.style,
        model=base_plan.model,
        provider_parameter_schema=base_plan.provider_parameter_schema,
        thinking=base_plan.thinking,
        reasoning_effort=base_plan.reasoning_effort,
        max_tokens=base_plan.max_tokens,
        presentation_order=order,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
        prompt_profile="legacy_stability_v3",
        source_candidate_path=base_plan.source_candidate_path,
        campaign_id=campaign_id,
        trial_id=trial_id,
        research_only=True,
    )
    if plan.universe.input_sha256 != base_plan.universe.input_sha256:
        raise ValueError("candidate input changed while building stability campaign")
    prefix = f"trials/{trial_id}"
    prompt_path = f"{prefix}/prompt.txt"
    trial_path = f"{prefix}/trial.json"
    trial: dict[str, object] = {
        "schema_version": STABILITY_SCHEMA_VERSION,
        "artifact_type": "ai_stability_trial",
        "campaign_id": campaign_id,
        "trial_id": trial_id,
        "market": plan.market,
        "provider": plan.provider,
        "model": plan.model,
        "provider_parameters": _provider_parameters(plan),
        "provider_parameter_schema": plan.provider_parameter_schema,
        "prompt_version": plan.prompt_version,
        "prompt_profile": plan.prompt_profile,
        "selection_as_of": plan.universe.selection_as_of.isoformat(),
        "style": plan.style,
        "top_n": plan.top_n,
        "seed": seed,
        "candidate_path": candidate_name,
        "source_candidate_path": plan.source_candidate_path,
        "input_sha256": plan.universe.input_sha256,
        "presentation_order": list(plan.presentation_order),
        "symbol_aliases": dict(plan.symbol_aliases),
        "name_aliases": dict(plan.name_aliases),
        "identity_mapping": list(identity_mapping),
        "prompt_path": prompt_path,
        "prompt_sha256": _digest(plan.prompt.encode()),
        "api_calls": 0,
    }
    files[prompt_path] = plan.prompt.encode()
    files[trial_path] = _json_bytes(trial)
    return {
        "trial_id": trial_id,
        "trial_path": trial_path,
        "prompt_sha256": trial["prompt_sha256"],
        "anonymous_codes": bool(symbol_aliases),
    }


def _fixed_shuffles(
    symbols: tuple[str, ...], seeds: tuple[int, int, int]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    shuffled: list[tuple[str, ...]] = []
    for seed in seeds:
        order = list(symbols)
        random.Random(seed).shuffle(order)
        shuffled.append(tuple(order))
    if any(order == symbols for order in shuffled) or len(set(shuffled)) != 3:
        raise ValueError(
            "fixed seeds did not produce three distinct noncanonical orders"
        )
    return cast(
        tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
        tuple(shuffled),
    )


def _shuffle_seeds(value: Sequence[int]) -> tuple[int, int, int]:
    seeds = tuple(value)
    if len(seeds) != 3 or any(
        isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds
    ):
        raise ValueError("shuffle_seeds must contain exactly three integers")
    if len(set(seeds)) != 3:
        raise ValueError("shuffle_seeds must be unique")
    return seeds


def _exchange_files(
    plan: SelectionPlan, exchange: ProviderExchange
) -> dict[str, bytes]:
    candidate_name = f"candidate_input{plan.universe.path.suffix.lower()}"
    candidate_payload = read_plan_candidate_snapshot(plan)
    request_envelope = {
        "method": exchange.request_method,
        "endpoint": exchange.endpoint,
        "headers": dict(exchange.request_headers),
        "timeout_seconds": exchange.timeout_seconds,
        "body_path": "provider_request_body.json",
        "body_sha256": _digest(exchange.request_body),
    }
    files = {
        candidate_name: candidate_payload,
        "numeric_ranking.json": _numeric_ranking_bytes(plan),
        "prompt.txt": plan.prompt.encode(),
        "http_request_envelope.json": _json_bytes(request_envelope),
        "provider_request_body.json": exchange.request_body,
        "provider_response_body.bin": exchange.response_body,
    }
    if exchange.response_text is not None:
        files["model_response.txt"] = exchange.response_text.encode()
    return files


def _selection_manifest(
    plan: SelectionPlan,
    exchange: ProviderExchange,
    files: dict[str, bytes],
    *,
    status: Literal["complete", "rejected"],
    available_at: datetime,
    selection_path: str | None,
    rejection: str | None,
    contracts: Mapping[str, str],
) -> dict[str, object]:
    candidate_name = f"candidate_input{plan.universe.path.suffix.lower()}"
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "artifact_type": "ai_selection_evidence",
        "status": status,
        "generated_at": available_at.astimezone(timezone.utc).isoformat(),
        "available_at": available_at.astimezone(timezone.utc).isoformat(),
        "candidate_available_at": _candidate_available_at(plan),
        "selection_as_of": plan.universe.selection_as_of.isoformat(),
        "market": plan.market,
        "provider": exchange.provider,
        "model": exchange.model,
        "requested_model_alias": exchange.model,
        "response_model": exchange.actual_model,
        "response_extraction_error": exchange.extraction_error,
        "provider_parameters": _provider_parameters(plan),
        "provider_parameter_schema": plan.provider_parameter_schema,
        "campaign_id": plan.campaign_id,
        "trial_id": plan.trial_id,
        "plan_sha256": plan.plan_sha256,
        **contracts,
        "ranking_diagnostic_path": (
            "ranking_diagnostic.json"
            if contracts["ranking_contract"] == "passed"
            and contracts["publication_contract"] == "failed"
            else None
        ),
        "prompt_version": plan.prompt_version,
        "prompt_profile": plan.prompt_profile,
        **plan.ranking_policy_fields,
        "style": plan.style,
        "top_n": plan.top_n,
        "candidate_path": candidate_name,
        "source_candidate_path": plan.source_candidate_path,
        "input_contract": plan.universe.input_contract,
        "input_count": len(plan.universe.candidates),
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "prompt_sha256": _digest(plan.prompt.encode()),
        "response_sha256": (
            _digest(exchange.response_text.encode())
            if exchange.response_text is not None
            else None
        ),
        "presentation_order": list(plan.presentation_order),
        "symbol_aliases": dict(plan.symbol_aliases),
        "name_aliases": dict(plan.name_aliases),
        "alias_maps_sha256": alias_maps_sha256(
            dict(plan.symbol_aliases), dict(plan.name_aliases)
        ),
        "selection_path": selection_path,
        "rejection": rejection,
        "api_calls": 1,
        "eligible_as_oos_evidence": False,
        "research_only": plan.research_only or plan.prompt_profile != "production_v4",
        "files": _file_records(files),
    }


def _file_records(files: Mapping[str, bytes]) -> dict[str, dict[str, object]]:
    return {
        path: {"sha256": _digest(payload), "bytes": len(payload)}
        for path, payload in sorted(files.items())
    }


def _write_bundle(
    output_dir: str | Path,
    files: dict[str, bytes],
    manifest: dict[str, object],
) -> Path:
    root = _reserve_directory(output_dir)
    _write_files(root, files)
    _write_exclusive(root / "manifest.json", _json_bytes(manifest))
    validate_selection_evidence(root)
    return root


def _reserve_directory(output_dir: str | Path) -> Path:
    root = Path(output_dir).expanduser().resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FileExistsError(
            f"evidence directory already exists; refusing overwrite: {root}"
        ) from exc
    return root


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, payload in sorted(files.items()):
        destination = _inside(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_exclusive(destination, payload)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"trial {field} must be a string array")
    return cast(list[str], value)


def _integer_list(value: object, field: str) -> list[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValueError(f"trial {field} must be an integer array")
    return cast(list[int], value)


def _strict_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"trial {field} must be an integer")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "STABILITY_SCHEMA_VERSION",
    "load_stability_trial",
    "validate_selection_evidence",
    "validate_stability_campaign",
    "write_rejected_selection_evidence",
    "write_selection_evidence",
    "write_stability_campaign",
]
