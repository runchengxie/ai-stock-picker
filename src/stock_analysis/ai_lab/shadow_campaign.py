"""Append-only bounded-ranking v2 shadow repetitions and deterministic consensus."""

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
from statistics import median
from typing import Literal, cast
from zoneinfo import ZoneInfo

from .bundle_paths import safe_bundle_path
from .contracts import (
    SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_MIN_VALID_REPETITIONS,
    SHADOW_REPETITION_NAMES,
    SHADOW_REPETITIONS,
    SHADOW_TOMBSTONE_REASONS,
    RankingModelSelection,
)
from .evidence_consistency import numeric_ranking_bytes
from .evidence_contracts import ranking_diagnostic_bytes, selection_contracts
from .providers import (
    ProviderError,
    ProviderExchange,
    ReasoningEffort,
    ThinkingMode,
    call_deepseek_exchange,
    call_openai_responses_exchange,
)
from .ranking_policy import policy_partitions
from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
)
from .selection import SelectionPlan, read_plan_candidate_snapshot
from .shadow_exchange_validation import validate_shadow_exchange
from .shadow_validation import (
    read_shadow_ranking,
    validate_shadow_campaign,
    validate_shadow_day,
    validate_shadow_repetition,
)

ShadowProvider = Literal["deepseek", "openai"]
RepetitionStatus = Literal["complete", "tombstone"]
ShadowCaller = Callable[[SelectionPlan, "ShadowModel", int, float], ProviderExchange]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGING_DIRECTORY = ".ai-stock-picker-shadow-staging"


@dataclass(frozen=True, slots=True)
class ShadowModel:
    """Frozen research-provider parameters for one campaign model partition."""

    provider: ShadowProvider
    model: str
    max_output_tokens: int = 8_192
    thinking: ThinkingMode = "disabled"
    reasoning_effort: ReasoningEffort | None = None

    def __post_init__(self) -> None:
        if self.provider not in {"deepseek", "openai"}:
            raise ValueError("shadow provider must be deepseek or openai")
        if _MODEL.fullmatch(self.model) is None:
            raise ValueError("shadow model contains unsupported characters")
        if isinstance(self.max_output_tokens, bool) or not isinstance(
            self.max_output_tokens, int
        ):
            raise ValueError("shadow max_output_tokens must be an integer")
        if not 1 <= self.max_output_tokens <= 65_536:
            raise ValueError("shadow max_output_tokens must be between 1 and 65536")
        if self.provider == "openai" and (
            self.thinking != "disabled" or self.reasoning_effort is not None
        ):
            raise ValueError("OpenAI shadow does not accept DeepSeek thinking fields")
        if self.provider == "deepseek":
            if self.thinking == "enabled" and self.reasoning_effort not in {
                "high",
                "max",
            }:
                raise ValueError("DeepSeek thinking requires high or max effort")
            if self.thinking == "disabled" and self.reasoning_effort is not None:
                raise ValueError("DeepSeek reasoning_effort requires thinking enabled")

    @property
    def partition(self) -> str:
        return f"{self.provider}--{self.model}"

    def contract_record(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_output_tokens": self.max_output_tokens,
            "thinking": self.thinking if self.provider == "deepseek" else None,
            "reasoning_effort": (
                self.reasoning_effort if self.provider == "deepseek" else None
            ),
        }


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
    shadow_model: ShadowModel,
    generated_at: datetime | None = None,
    timeout: float = 120,
    caller: ShadowCaller | None = None,
) -> ShadowDayResult:
    """Execute exactly three repetitions and terminalize every expected unit."""

    created = _validate_run(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        generated_at=generated_at,
        timeout=timeout,
    )
    day_root = shadow_day_path(
        output_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
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
        )
        statuses.append(status)
    consensus = _write_consensus(
        plan,
        day_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=created,
    )
    validate_shadow_day(day_root)
    return ShadowDayResult(day_root, tuple(statuses), consensus)


def finalize_shadow_day(
    plan: SelectionPlan,
    output_root: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    generated_at: datetime | None = None,
) -> ShadowDayResult:
    """Watchdog-terminalize missing repetitions without making provider calls."""

    created = _validate_run(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        generated_at=generated_at,
        timeout=1.0,
    )
    day_root = shadow_day_path(
        output_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
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
            )
        )
    consensus = _write_consensus(
        plan,
        day_root,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=created,
    )
    validate_shadow_day(day_root)
    return ShadowDayResult(day_root, tuple(statuses), consensus)


def shadow_day_path(
    output_root: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
) -> Path:
    """Resolve the owner-defined campaign/model/date partition."""

    _validate_identifier(campaign_id, "campaign_id")
    root = Path(output_root).expanduser().resolve()
    return root / campaign_id / shadow_model.partition / signal_date.isoformat()


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
            response_schema=RankingModelSelection.model_json_schema(),
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
    if plan.market != "CN" or plan.prompt_profile != "bounded_ranking_v2":
        raise ValueError("shadow campaign requires a CN bounded_ranking_v2 plan")
    if plan.prompt_version != BOUNDED_RANKING_V2_PROMPT_VERSION:
        raise ValueError("shadow campaign prompt version is not the owner .7 contract")
    if plan.ranking_policy != BOUNDED_RANKING_V2_POLICY:
        raise ValueError("shadow campaign ranking policy is inconsistent")
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
) -> RepetitionStatus:
    files = _repetition_files(plan, exchange)
    contracts = {
        "transport_contract": "failed",
        "ranking_contract": "not_evaluated",
        "publication_contract": "not_evaluated",
    }
    ranking: bytes | None = None
    if exchange is not None and tombstone_reason is None:
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
    status: RepetitionStatus = (
        "complete" if contracts["ranking_contract"] == "passed" else "tombstone"
    )
    if status == "tombstone":
        tombstone_reason = tombstone_reason or "ranking_contract_failed"
        _validate_tombstone_reason(tombstone_reason)
    else:
        tombstone_reason = None
    manifest = _common_manifest(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        shadow_model=shadow_model,
        generated_at=generated_at,
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
    _write_bundle(output_dir, files, manifest)
    validate_shadow_repetition(output_dir)
    return status


def _ranking_from_response(
    plan: SelectionPlan, exchange: ProviderExchange
) -> tuple[str, ...]:
    if exchange.response_text is None:
        raise ValueError("ranking response text is unavailable")
    from .selection import ranking_symbols

    return ranking_symbols(plan, exchange.response_text)


def _repetition_files(
    plan: SelectionPlan, exchange: ProviderExchange | None
) -> dict[str, bytes]:
    candidate_name = f"candidate_input{plan.universe.path.suffix.lower()}"
    files = {
        candidate_name: read_plan_candidate_snapshot(plan),
        "numeric_ranking.json": numeric_ranking_bytes(plan),
        "prompt.txt": plan.prompt.encode(),
    }
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
) -> dict[str, object]:
    return {
        "schema_version": SHADOW_CAMPAIGN_SCHEMA_VERSION,
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
        "ranking_policy": plan.ranking_policy_record,
        "strict_point_in_time": False,
        "eligible_as_oos_evidence": False,
        "research_only": True,
    }


def _write_consensus(
    plan: SelectionPlan,
    day_root: Path,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel,
    generated_at: datetime,
) -> RepetitionStatus:
    valid: list[tuple[int, tuple[str, ...]]] = []
    for repetition, name in enumerate(SHADOW_REPETITION_NAMES, start=1):
        root = day_root / name
        manifest = validate_shadow_repetition(root)
        if manifest["status"] == "complete":
            valid.append((repetition, read_shadow_ranking(root, manifest)))
    files: dict[str, bytes] = {}
    status: RepetitionStatus
    reason: str | None
    if len(valid) >= SHADOW_MIN_VALID_REPETITIONS:
        payload = _consensus_payload(plan, valid)
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
    )
    manifest.update(
        {
            "artifact_type": "ai_shadow_consensus",
            "status": status,
            "repetitions": SHADOW_REPETITIONS,
            "min_valid_repetitions": SHADOW_MIN_VALID_REPETITIONS,
            "valid_repetitions": [item[0] for item in valid],
            "consensus_path": "consensus.json" if status == "complete" else None,
            "tombstone_reason": reason,
            "files": _file_records(files),
        }
    )
    _write_bundle(day_root / "consensus", files, manifest)
    return status


def _consensus_payload(
    plan: SelectionPlan, valid: list[tuple[int, tuple[str, ...]]]
) -> dict[str, object]:
    locked, _boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V2_POLICY)
    tallies: dict[str, dict[str, object]] = {}
    for _repetition, symbols in valid:
        if symbols[: len(locked)] != locked:
            raise ValueError("valid repetition changed the locked Numeric prefix")
        for boundary_order, symbol in enumerate(symbols[len(locked) :], start=1):
            tally = tallies.setdefault(
                symbol, {"votes": 0, "ranking_points": 0, "orders": []}
            )
            tally["votes"] = cast(int, tally["votes"]) + 1
            tally["ranking_points"] = cast(int, tally["ranking_points"]) + (
                4 - boundary_order
            )
            cast(list[int], tally["orders"]).append(boundary_order)
    records = [
        {
            "symbol": symbol,
            "votes": cast(int, tally["votes"]),
            "ranking_points": cast(int, tally["ranking_points"]),
            "median_order": float(median(cast(list[int], tally["orders"]))),
        }
        for symbol, tally in tallies.items()
    ]
    records.sort(
        key=lambda item: (
            -cast(int, item["votes"]),
            -cast(int, item["ranking_points"]),
            cast(float, item["median_order"]),
            cast(str, item["symbol"]),
        )
    )
    winners = tuple(cast(str, item["symbol"]) for item in records[:3])
    return {
        "schema_version": SHADOW_CAMPAIGN_SCHEMA_VERSION,
        "artifact_type": "ai_shadow_consensus_ranking",
        "method": "votes_then_borda_then_median_then_symbol_v1",
        "valid_repetitions": [item[0] for item in valid],
        "locked_prefix": list(locked),
        "boundary_winners": list(winners),
        "selected_symbols": [*locked, *winners],
        "boundary_tallies": records,
    }


def _write_bundle(
    output_dir: Path, files: Mapping[str, bytes], manifest: Mapping[str, object]
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(
            f"shadow partition already exists; refusing overwrite: {output_dir}"
        )
    staging_parent = output_dir.parents[3] / _STAGING_DIRECTORY
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
    "validate_shadow_campaign",
    "validate_shadow_day",
    "validate_shadow_repetition",
]
