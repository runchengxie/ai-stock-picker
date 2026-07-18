"""Append-only owner shadow repetitions and deterministic consensus."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast
from zoneinfo import ZoneInfo

from .bundle_paths import safe_bundle_path
from .contracts import (
    SHADOW_MIN_VALID_REPETITIONS,
    SHADOW_REPETITION_NAMES,
    SHADOW_REPETITIONS,
    SHADOW_TOMBSTONE_REASONS,
)
from .evidence_consistency import numeric_ranking_bytes
from .evidence_contracts import ranking_diagnostic_bytes, selection_contracts
from .providers import (
    ProviderError,
    ProviderExchange,
    call_deepseek_exchange,
    call_openai_responses_exchange,
)
from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
    BOUNDED_RANKING_V3_POLICY,
    BOUNDED_RANKING_V3_PROMPT_VERSION,
    RISK_VETO_POLICY,
    RISK_VETO_PROMPT_VERSION,
)
from .selection import SelectionPlan, read_plan_candidate_snapshot
from .shadow_contract import (
    RiskDecision,
    ShadowArm,
    bounded_consensus_payload,
    parse_shadow_response,
    risk_decision_payload,
    risk_veto_consensus_payload,
    shadow_arm_for_profile,
    shadow_response_schema,
    shadow_response_schema_name,
    shadow_schema_for_profile,
)
from .shadow_exchange_validation import validate_shadow_exchange
from .shadow_lineage import (
    ShadowDecisionPlan,
    ShadowLaunchBinding,
    ShadowLaunchReceipt,
    ShadowModel,
    resolve_shadow_launch_binding,
    validate_shadow_launch_time,
)
from .shadow_validation import (
    read_shadow_ranking,
    read_shadow_risk_decision,
    validate_shadow_day,
    validate_shadow_repetition,
)

ShadowProvider = Literal["deepseek", "openai"]
RepetitionStatus = Literal["complete", "tombstone"]
ShadowCaller = Callable[[SelectionPlan, "ShadowModel", int, float], ProviderExchange]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGING_DIRECTORY = ".ai-stock-picker-shadow-staging"


@dataclass(frozen=True, slots=True)
class ShadowDayResult:
    day_root: Path
    repetition_statuses: tuple[RepetitionStatus, ...]
    consensus_status: RepetitionStatus


def run_shadow_day(
    plan: SelectionPlan,
    output_root: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel | None = None,
    decision_plan: ShadowDecisionPlan | str | Path | None = None,
    launch_receipt: ShadowLaunchReceipt | str | Path | None = None,
    generated_at: datetime | None = None,
    timeout: float = 120,
    caller: ShadowCaller | None = None,
) -> ShadowDayResult:
    """Execute exactly three repetitions and terminalize every expected unit."""

    shadow_model, launch_binding = resolve_shadow_launch_binding(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        decision_plan=decision_plan,
        launch_receipt=launch_receipt,
        require_bound=caller is None,
    )
    created = _validate_run(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        generated_at=generated_at,
        timeout=timeout,
    )
    validate_shadow_launch_time(launch_binding, created)
    day_root = shadow_day_path(
        output_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        arm=(
            None
            if plan.prompt_profile == "bounded_ranking_v2"
            else shadow_arm_for_profile(plan.prompt_profile)
        ),
    )
    if day_root.exists() or day_root.is_symlink():
        raise FileExistsError(
            f"shadow day already exists; refusing overwrite: {day_root}"
        )
    invoke = caller or call_shadow_provider
    statuses: list[RepetitionStatus] = []
    for repetition in range(1, SHADOW_REPETITIONS + 1):
        exchange: ProviderExchange | None = None
        try:
            exchange = invoke(plan, shadow_model, repetition, timeout)
        except (OSError, ProviderError, TimeoutError, ValueError):
            tombstone_reason = "provider_call_failed"
        else:
            try:
                validate_shadow_exchange(
                    exchange,
                    prompt=plan.prompt,
                    provider=shadow_model.provider,
                    model_parameters=shadow_model.contract_record(),
                    response_schema=shadow_response_schema(plan),
                    response_schema_name=shadow_response_schema_name(plan),
                )
            except (OSError, ProviderError, TimeoutError, ValueError):
                exchange = None
                tombstone_reason = "transport_contract_failed"
            else:
                tombstone_reason = None
        status = _write_repetition(
            plan,
            day_root / SHADOW_REPETITION_NAMES[repetition - 1],
            campaign_id=campaign_id,
            signal_date=signal_date,
            shadow_model=shadow_model,
            repetition=repetition,
            generated_at=created,
            exchange=exchange,
            tombstone_reason=tombstone_reason,
            launch_binding=launch_binding,
        )
        statuses.append(status)
    consensus = _write_consensus(
        plan,
        day_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=created,
        launch_binding=launch_binding,
    )
    validate_shadow_day(day_root)
    return ShadowDayResult(day_root, tuple(statuses), consensus)


def finalize_shadow_day(
    plan: SelectionPlan,
    output_root: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel | None = None,
    decision_plan: ShadowDecisionPlan | str | Path | None = None,
    launch_receipt: ShadowLaunchReceipt | str | Path | None = None,
    generated_at: datetime | None = None,
) -> ShadowDayResult:
    """Watchdog-terminalize missing repetitions without making provider calls."""

    shadow_model, launch_binding = resolve_shadow_launch_binding(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        decision_plan=decision_plan,
        launch_receipt=launch_receipt,
        require_bound=True,
    )
    created = _validate_run(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        generated_at=generated_at,
        timeout=1.0,
    )
    validate_shadow_launch_time(launch_binding, created)
    day_root = shadow_day_path(
        output_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        arm=(
            None
            if plan.prompt_profile == "bounded_ranking_v2"
            else shadow_arm_for_profile(plan.prompt_profile)
        ),
    )
    consensus_root = day_root / "consensus"
    if consensus_root.exists() or consensus_root.is_symlink():
        summary = validate_shadow_day(day_root)
        statuses = cast(list[str], summary["repetition_statuses"])
        return ShadowDayResult(
            day_root,
            cast(tuple[RepetitionStatus, ...], tuple(statuses)),
            cast(RepetitionStatus, summary["consensus_status"]),
        )
    statuses: list[RepetitionStatus] = []
    for repetition, name in enumerate(SHADOW_REPETITION_NAMES, start=1):
        root = day_root / name
        if root.exists() or root.is_symlink():
            manifest = validate_shadow_repetition(root)
            statuses.append(cast(RepetitionStatus, manifest["status"]))
            continue
        statuses.append(
            _write_repetition(
                plan,
                root,
                campaign_id=campaign_id,
                signal_date=signal_date,
                shadow_model=shadow_model,
                repetition=repetition,
                generated_at=created,
                exchange=None,
                tombstone_reason="watchdog_missing_repetition",
                launch_binding=launch_binding,
            )
        )
    consensus = _write_consensus(
        plan,
        day_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=created,
        launch_binding=launch_binding,
    )
    validate_shadow_day(day_root)
    return ShadowDayResult(day_root, tuple(statuses), consensus)


def shadow_day_path(
    output_root: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    arm: ShadowArm | None = None,
) -> Path:
    """Resolve the owner-defined campaign/model/date partition."""

    _validate_identifier(campaign_id, "campaign_id")
    root = Path(output_root).expanduser().resolve()
    base = root / campaign_id
    if arm is not None:
        base /= arm
    return base / shadow_model.partition / signal_date.isoformat()


def call_shadow_provider(
    plan: SelectionPlan,
    shadow_model: ShadowModel,
    _repetition: int,
    timeout: float,
) -> ProviderExchange:
    """Dispatch one research-only repetition using the frozen prompt bytes."""

    read_plan_candidate_snapshot(plan)
    if shadow_model.provider == "openai":
        return call_openai_responses_exchange(
            plan.prompt,
            response_schema=shadow_response_schema(plan),
            response_schema_name=shadow_response_schema_name(plan),
            model=shadow_model.model,
            max_output_tokens=shadow_model.max_output_tokens,
            timeout=timeout,
        )
    return call_deepseek_exchange(
        plan.prompt,
        model=shadow_model.model,
        thinking=shadow_model.thinking,
        reasoning_effort=shadow_model.reasoning_effort,
        max_tokens=shadow_model.max_output_tokens,
        parameter_schema="explicit_v2",
        timeout=timeout,
    )


def _validate_run(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    signal_date: date,
    generated_at: datetime | None,
    timeout: float,
) -> datetime:
    _validate_identifier(campaign_id, "campaign_id")
    if plan.market != "CN":
        raise ValueError("shadow campaign requires a CN research plan")
    expected = {
        "bounded_ranking_v2": (
            BOUNDED_RANKING_V2_PROMPT_VERSION,
            BOUNDED_RANKING_V2_POLICY,
            None,
        ),
        "bounded_ranking_v3": (
            BOUNDED_RANKING_V3_PROMPT_VERSION,
            BOUNDED_RANKING_V3_POLICY,
            None,
        ),
        "risk_veto_v1": (RISK_VETO_PROMPT_VERSION, None, RISK_VETO_POLICY),
    }.get(plan.prompt_profile)
    if expected is None:
        raise ValueError("shadow campaign requires a supported owner shadow profile")
    expected_version, ranking_policy, risk_policy = expected
    if plan.prompt_version != expected_version:
        raise ValueError("shadow campaign prompt version is not the owner contract")
    if plan.ranking_policy != ranking_policy or plan.risk_veto_policy != risk_policy:
        raise ValueError("shadow campaign decision policy is inconsistent")
    if plan.symbol_aliases or plan.name_aliases:
        raise ValueError("shadow campaign does not accept identity aliases")
    if plan.plan_sha256 is None or _SHA256.fullmatch(plan.plan_sha256) is None:
        raise ValueError("shadow campaign requires a frozen plan digest")
    if plan.campaign_id is not None and plan.campaign_id != campaign_id:
        raise ValueError("shadow campaign_id differs from the frozen plan")
    if signal_date != plan.universe.selection_as_of:
        raise ValueError("shadow signal_date must equal the frozen plan selection date")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("shadow timeout must be a positive finite number")
    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("shadow generated_at must include a UTC offset")
    local = created.astimezone(ZoneInfo("Asia/Shanghai"))
    if local.date() < signal_date or (
        local.date() == signal_date
        and local.timetz().replace(tzinfo=None) < time(16, 0)
    ):
        raise ValueError("shadow execution must occur after the signal-date close")
    if (
        plan.universe.source_generated_at is not None
        and plan.universe.source_generated_at > created
    ):
        raise ValueError("candidate manifest was generated after shadow execution")
    read_plan_candidate_snapshot(plan)
    return created.astimezone(timezone.utc)


def _write_repetition(
    plan: SelectionPlan,
    output_dir: Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    repetition: int,
    generated_at: datetime,
    exchange: ProviderExchange | None,
    tombstone_reason: str | None = None,
    launch_binding: ShadowLaunchBinding | None = None,
) -> RepetitionStatus:
    files = _repetition_files(plan, exchange, launch_binding)
    ranking: bytes | None = None
    decision: bytes | None = None
    if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto":
        contracts = {
            "transport_contract": "failed",
            "ranking_contract": "not_evaluated",
            "decision_contract": "not_evaluated",
            "publication_contract": "not_applicable",
        }
    else:
        contracts = {
            "transport_contract": "failed",
            "ranking_contract": "not_evaluated",
            "publication_contract": "not_evaluated",
        }
    if exchange is not None and tombstone_reason is None:
        if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto":
            if exchange.response_text is None:
                tombstone_reason = "transport_contract_failed"
            else:
                contracts["transport_contract"] = "passed"
                try:
                    kind, parsed = parse_shadow_response(plan, exchange.response_text)
                    if kind != "risk_veto" or not isinstance(parsed, tuple):
                        raise ValueError("risk-veto response parser returned wrong arm")
                    risk = cast(RiskDecision, parsed)
                except ValueError:
                    contracts["decision_contract"] = "failed"
                    tombstone_reason = "decision_contract_failed"
                else:
                    contracts["decision_contract"] = "passed"
                    decision = _json_bytes(risk_decision_payload(risk))
                    files["decision.json"] = decision
        else:
            contracts, diagnostic = selection_contracts(
                plan, exchange, generated_at=generated_at
            )
            if contracts["ranking_contract"] == "passed":
                ranking = diagnostic or ranking_diagnostic_bytes(
                    _ranking_from_response(plan, exchange)
                )
                files["ranking.json"] = ranking
            elif tombstone_reason is None:
                tombstone_reason = (
                    "transport_contract_failed"
                    if contracts["transport_contract"] == "failed"
                    else "ranking_contract_failed"
                )
    passed = (
        contracts.get("decision_contract") == "passed"
        if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto"
        else contracts["ranking_contract"] == "passed"
    )
    status: RepetitionStatus = "complete" if passed else "tombstone"
    if status == "tombstone":
        tombstone_reason = tombstone_reason or (
            "decision_contract_failed"
            if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto"
            else "ranking_contract_failed"
        )
        _validate_tombstone_reason(tombstone_reason)
    else:
        tombstone_reason = None
    manifest = _repetition_manifest(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        repetition=repetition,
        generated_at=generated_at,
        status=status,
        contracts=contracts,
        ranking=ranking,
        decision=decision,
        tombstone_reason=tombstone_reason,
        exchange=exchange,
        files=files,
        launch_binding=launch_binding,
    )
    _write_bundle(output_dir, files, manifest)
    validate_shadow_repetition(output_dir)
    return status


def _repetition_manifest(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    repetition: int,
    generated_at: datetime,
    status: RepetitionStatus,
    contracts: Mapping[str, str],
    ranking: bytes | None,
    decision: bytes | None,
    tombstone_reason: str | None,
    exchange: ProviderExchange | None,
    files: Mapping[str, bytes],
    launch_binding: ShadowLaunchBinding | None,
) -> dict[str, object]:
    manifest = _common_manifest(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=generated_at,
        launch_binding=launch_binding,
    )
    manifest.update(
        {
            "artifact_type": "ai_shadow_repetition",
            "status": status,
            "repetition": repetition,
            **contracts,
            "ranking_path": "ranking.json" if ranking is not None else None,
            "tombstone_reason": tombstone_reason,
            "requested_model": shadow_model.model,
            "actual_model": exchange.actual_model if exchange is not None else None,
            "refusal": exchange.refusal if exchange is not None else None,
            "usage": exchange.usage if exchange is not None else None,
            "response_extraction_error": (
                exchange.extraction_error if exchange is not None else None
            ),
            "files": _file_records(files),
        }
    )
    if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto":
        manifest["decision_path"] = "decision.json" if decision is not None else None
    return manifest


def _ranking_from_response(
    plan: SelectionPlan, exchange: ProviderExchange
) -> tuple[str, ...]:
    if exchange.response_text is None:
        raise ValueError("ranking response text is unavailable")
    from .selection import ranking_symbols

    return ranking_symbols(plan, exchange.response_text)


def _repetition_files(
    plan: SelectionPlan,
    exchange: ProviderExchange | None,
    launch_binding: ShadowLaunchBinding | None,
) -> dict[str, bytes]:
    candidate_name = f"candidate_input{plan.universe.path.suffix.lower()}"
    files = {
        candidate_name: read_plan_candidate_snapshot(plan),
        "numeric_ranking.json": numeric_ranking_bytes(plan),
        "prompt.txt": plan.prompt.encode(),
    }
    if launch_binding is not None:
        files.update(
            {
                "decision-plan.json": launch_binding.decision_plan.artifact_bytes,
                "launch-receipt.json": launch_binding.launch_receipt.artifact_bytes,
            }
        )
    if exchange is None:
        return files
    envelope = {
        "endpoint": exchange.endpoint,
        "method": exchange.request_method,
        "headers": dict(exchange.request_headers),
        "timeout_seconds": exchange.timeout_seconds,
    }
    files.update(
        {
            "http_request_envelope.json": _json_bytes(envelope),
            "provider_request_body.json": exchange.request_body,
            "provider_response_body.bin": exchange.response_body,
        }
    )
    if exchange.response_text is not None:
        files["model_response.txt"] = exchange.response_text.encode()
    return files


def _common_manifest(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    generated_at: datetime,
    launch_binding: ShadowLaunchBinding | None,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": shadow_schema_for_profile(plan.prompt_profile),
        "campaign_id": campaign_id,
        "signal_date": signal_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "provider": shadow_model.provider,
        "model_partition": shadow_model.partition,
        "model_parameters": shadow_model.contract_record(),
        "prompt_profile": plan.prompt_profile,
        "prompt_version": plan.prompt_version,
        "prompt_sha256": _digest(plan.prompt.encode()),
        "plan_sha256": plan.plan_sha256,
        "style": plan.style,
        "top_n": plan.top_n,
        "candidate_snapshot_path": (
            f"candidate_input{plan.universe.path.suffix.lower()}"
        ),
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
        "input_contract": plan.universe.input_contract,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "strict_point_in_time": False,
        "eligible_as_oos_evidence": False,
        "research_only": True,
    }
    if plan.prompt_profile == "bounded_ranking_v2":
        manifest["ranking_policy"] = plan.ranking_policy_record
    else:
        manifest.update(
            {
                "arm": shadow_arm_for_profile(plan.prompt_profile),
                "evidence_status": (
                    launch_binding.evidence_status
                    if launch_binding is not None
                    else "legacy_unbound"
                ),
                "decision_plan_sha256": (
                    launch_binding.decision_plan.decision_plan_sha256
                    if launch_binding is not None
                    else None
                ),
                "launch_receipt_sha256": (
                    launch_binding.launch_receipt.launch_receipt_sha256
                    if launch_binding is not None
                    else None
                ),
                **plan.decision_policy_fields,
            }
        )
    return manifest


def _write_consensus(
    plan: SelectionPlan,
    day_root: Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    generated_at: datetime,
    launch_binding: ShadowLaunchBinding | None,
) -> RepetitionStatus:
    arm = shadow_arm_for_profile(plan.prompt_profile)
    valid_rankings: list[tuple[int, tuple[str, ...]]] = []
    valid_decisions: list[tuple[int, RiskDecision]] = []
    for repetition, name in enumerate(SHADOW_REPETITION_NAMES, start=1):
        root = day_root / name
        manifest = validate_shadow_repetition(root)
        if manifest["status"] == "complete":
            if arm == "risk_veto":
                valid_decisions.append(
                    (repetition, read_shadow_risk_decision(root, manifest))
                )
            else:
                valid_rankings.append((repetition, read_shadow_ranking(root, manifest)))
    valid_repetitions = [
        item[0] for item in (valid_decisions if arm == "risk_veto" else valid_rankings)
    ]
    files: dict[str, bytes] = {}
    status: RepetitionStatus
    reason: str | None
    if len(valid_repetitions) >= SHADOW_MIN_VALID_REPETITIONS:
        payload = (
            risk_veto_consensus_payload(plan, valid_decisions)
            if arm == "risk_veto"
            else bounded_consensus_payload(plan, valid_rankings)
        )
        if payload is None:
            status = "tombstone"
            reason = "insufficient_consensus_agreement"
        else:
            files["consensus.json"] = _json_bytes(payload)
            status = "complete"
            reason = None
    else:
        status = "tombstone"
        reason = "insufficient_valid_repetitions"
    manifest = _common_manifest(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=generated_at,
        launch_binding=launch_binding,
    )
    manifest.update(
        {
            "artifact_type": "ai_shadow_consensus",
            "status": status,
            "repetitions": SHADOW_REPETITIONS,
            "min_valid_repetitions": SHADOW_MIN_VALID_REPETITIONS,
            "valid_repetitions": valid_repetitions,
            "consensus_path": "consensus.json" if status == "complete" else None,
            "tombstone_reason": reason,
            "files": _file_records(files),
        }
    )
    _write_bundle(day_root / "consensus", files, manifest)
    return status


def _write_bundle(
    output_dir: Path, files: Mapping[str, bytes], manifest: Mapping[str, object]
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(
            f"shadow partition already exists; refusing overwrite: {output_dir}"
        )
    has_arm_partition = output_dir.parents[2].name in {
        "bounded_ranking",
        "risk_veto",
    }
    output_root = output_dir.parents[4 if has_arm_partition else 3]
    staging_parent = output_root / _STAGING_DIRECTORY
    if staging_parent.is_symlink():
        raise ValueError("shadow staging directory cannot be a symbolic link")
    staging_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{output_dir.name}-", dir=staging_parent))
    published = False
    try:
        for relative, content in sorted(files.items()):
            destination = safe_bundle_path(staging, relative, label="shadow bundle")
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write_exclusive(destination, content)
        _write_exclusive(staging / "manifest.json", _json_bytes(manifest))
        _fsync_directory(staging)
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError(
                f"shadow partition already exists; refusing overwrite: {output_dir}"
            )
        try:
            os.rename(staging, output_dir)
        except FileExistsError as exc:
            raise FileExistsError(
                f"shadow partition already exists; refusing overwrite: {output_dir}"
            ) from exc
        published = True
        _fsync_directory(output_dir.parent)
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_records(files: Mapping[str, bytes]) -> dict[str, dict[str, object]]:
    return {
        relative: {"sha256": _digest(payload), "bytes": len(payload)}
        for relative, payload in sorted(files.items())
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    )


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _validate_identifier(value: str, field: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} contains unsupported characters")


def _validate_tombstone_reason(value: object) -> None:
    if value not in SHADOW_TOMBSTONE_REASONS:
        raise ValueError("shadow tombstone reason is invalid")


__all__ = [
    "ShadowDayResult",
    "ShadowModel",
    "call_shadow_provider",
    "finalize_shadow_day",
    "run_shadow_day",
    "shadow_day_path",
]
