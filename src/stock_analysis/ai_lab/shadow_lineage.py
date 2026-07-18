"""Immutable, content-addressed launch lineage for prospective shadow runs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from .bundle_paths import reject_symlink_path
from .contracts import SHADOW_MIN_VALID_REPETITIONS, SHADOW_REPETITIONS
from .evidence_consistency import numeric_ranking_bytes
from .providers import ReasoningEffort, ThinkingMode
from .selection import SelectionPlan, read_plan_candidate_snapshot
from .shadow_contract import ShadowArm, shadow_arm_for_profile

SHADOW_DECISION_PLAN_SCHEMA_VERSION = "1.0.0"
SHADOW_LAUNCH_RECEIPT_SCHEMA_VERSION = "1.0.0"

ShadowLaunchProvider = Literal["deepseek", "openai"]
ShadowProvider = ShadowLaunchProvider
EvidenceStatus = Literal["prospective_bound", "legacy_unbound"]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ShadowDecisionPlan:
    """Validated provider-neutral decision intent and its canonical digest."""

    path: Path
    artifact_bytes: bytes
    decision_plan_sha256: str
    campaign_id: str
    signal_date: date
    arm: ShadowArm
    prompt_profile: str
    prompt_version: str
    style: str
    top_n: int
    input_contract: str
    input_sha256: str
    candidate_symbols_sha256: str
    prompt_sha256: str
    numeric_ranking_sha256: str
    candidate_observation_date: str | None
    candidate_generated_at: str | None
    decision_policy: dict[str, object]


@dataclass(frozen=True, slots=True)
class ShadowLaunchReceipt:
    """Validated provider-specific authorization for one decision plan."""

    path: Path
    artifact_bytes: bytes
    launch_receipt_sha256: str
    decision_plan_sha256: str
    campaign_id: str
    signal_date: date
    arm: ShadowArm
    input_sha256: str
    candidate_symbols_sha256: str
    prompt_sha256: str
    provider: ShadowLaunchProvider
    model_parameters: dict[str, object]
    model_partition: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class ShadowModel:
    """Provider parameters authorized by one shadow launch receipt."""

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
class ShadowLaunchBinding:
    """Fully validated prospective launch context."""

    decision_plan: ShadowDecisionPlan
    launch_receipt: ShadowLaunchReceipt

    @property
    def evidence_status(self) -> EvidenceStatus:
        return "prospective_bound"


def resolve_shadow_launch_binding(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    signal_date: date,
    shadow_model: ShadowModel | None,
    decision_plan: ShadowDecisionPlan | str | Path | None,
    launch_receipt: ShadowLaunchReceipt | str | Path | None,
    require_bound: bool,
) -> tuple[ShadowModel, ShadowLaunchBinding | None]:
    """Validate lineage and derive the only model allowed for this partition."""

    if (decision_plan is None) != (launch_receipt is None):
        raise ValueError(
            "prospective shadow requires both decision plan and launch receipt"
        )
    if decision_plan is None or launch_receipt is None:
        if require_bound and plan.prompt_profile in {
            "bounded_ranking_v3",
            "risk_veto_v1",
        }:
            raise ValueError(
                "prospective Prompt .8 shadow requires a provider-neutral decision "
                "plan and immutable launch receipt"
            )
        if shadow_model is None:
            raise ValueError("legacy shadow requires an explicit shadow model")
        return shadow_model, None
    decision = _decision_plan_value(decision_plan)
    receipt = (
        launch_receipt
        if isinstance(launch_receipt, ShadowLaunchReceipt)
        else load_shadow_launch_receipt(launch_receipt)
    )
    validate_shadow_decision_plan(
        plan,
        decision,
        campaign_id=campaign_id,
        signal_date=signal_date,
    )
    validate_shadow_launch_receipt(decision, receipt)
    parameters = receipt.model_parameters
    receipt_model = ShadowModel(
        provider=receipt.provider,
        model=cast(str, parameters["model"]),
        max_output_tokens=cast(int, parameters["max_output_tokens"]),
        thinking=cast(ThinkingMode, parameters["thinking"] or "disabled"),
        reasoning_effort=cast(ReasoningEffort | None, parameters["reasoning_effort"]),
    )
    if receipt_model.partition != receipt.model_partition:
        raise ValueError("shadow model partition must be derived from launch receipt")
    if shadow_model is not None:
        _validate_supplied_model(shadow_model, receipt_model)
    return receipt_model, ShadowLaunchBinding(decision, receipt)


def validate_shadow_launch_time(
    launch_binding: ShadowLaunchBinding | None, generated_at: datetime
) -> None:
    """Require launch authorization to exist no later than execution."""

    if (
        launch_binding is not None
        and launch_binding.launch_receipt.issued_at > generated_at
    ):
        raise ValueError("shadow launch receipt was issued after execution")


def _validate_supplied_model(supplied: ShadowModel, receipt_model: ShadowModel) -> None:
    if supplied.provider != receipt_model.provider:
        raise ValueError("shadow provider differs from launch receipt")
    if supplied.model != receipt_model.model:
        raise ValueError("shadow model differs from launch receipt")
    if supplied.contract_record() != receipt_model.contract_record():
        raise ValueError("shadow model parameters differ from launch receipt")


def write_shadow_decision_plan(
    plan: SelectionPlan,
    output_dir: str | Path,
    *,
    campaign_id: str,
    signal_date: date,
) -> Path:
    """Write one provider-neutral `.8` decision plan without overwriting."""

    core = _decision_plan_core(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
    )
    payload = _content_addressed_payload(core)
    root = _reserve_directory(output_dir, "shadow decision plan")
    path = root / "decision-plan.json"
    _write_exclusive(path, _json_bytes(payload))
    load_shadow_decision_plan(path)
    return path


def load_shadow_decision_plan(path: str | Path) -> ShadowDecisionPlan:
    """Load and strictly validate one provider-neutral decision plan."""

    artifact_path, artifact_bytes, payload = _read_artifact(
        path, "decision-plan.json", "shadow decision plan"
    )
    expected_keys = {
        "schema_version",
        "artifact_type",
        "market",
        "campaign_id",
        "signal_date",
        "arm",
        "prompt_profile",
        "prompt_version",
        "style",
        "top_n",
        "input_contract",
        "input_sha256",
        "candidate_symbols_sha256",
        "prompt_sha256",
        "numeric_ranking_sha256",
        "candidate_observation_date",
        "candidate_generated_at",
        "repetitions",
        "min_valid_repetitions",
        "strict_point_in_time",
        "research_only",
        "decision_policy",
        "content_sha256",
    }
    if set(payload) != expected_keys:
        raise ValueError("shadow decision plan fields are invalid")
    if (
        payload.get("schema_version") != SHADOW_DECISION_PLAN_SCHEMA_VERSION
        or payload.get("artifact_type") != "ai_shadow_decision_plan"
        or payload.get("market") != "CN"
    ):
        raise ValueError("shadow decision plan contract is invalid")
    content_sha256 = _validate_content_sha256(payload, "shadow decision plan")
    campaign_id = _identifier(payload.get("campaign_id"), "campaign_id")
    signal_date = _date_value(payload.get("signal_date"), "signal_date")
    arm = _arm(payload.get("arm"))
    profile = _nonempty_string(payload.get("prompt_profile"), "prompt_profile")
    if shadow_arm_for_profile(profile) != arm or profile not in {
        "bounded_ranking_v3",
        "risk_veto_v1",
    }:
        raise ValueError("shadow decision plan arm/profile binding is invalid")
    if (
        payload.get("repetitions") != SHADOW_REPETITIONS
        or payload.get("min_valid_repetitions") != SHADOW_MIN_VALID_REPETITIONS
        or payload.get("strict_point_in_time") is not False
        or payload.get("research_only") is not True
    ):
        raise ValueError("shadow decision plan research contract is invalid")
    top_n = payload.get("top_n")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n != 10:
        raise ValueError("shadow decision plan top_n is invalid")
    policy = payload.get("decision_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow decision plan decision_policy is invalid")
    return ShadowDecisionPlan(
        path=artifact_path,
        artifact_bytes=artifact_bytes,
        decision_plan_sha256=content_sha256,
        campaign_id=campaign_id,
        signal_date=signal_date,
        arm=arm,
        prompt_profile=profile,
        prompt_version=_nonempty_string(
            payload.get("prompt_version"), "prompt_version"
        ),
        style=_nonempty_string(payload.get("style"), "style"),
        top_n=top_n,
        input_contract=_nonempty_string(
            payload.get("input_contract"), "input_contract"
        ),
        input_sha256=_digest_value(payload.get("input_sha256"), "input_sha256"),
        candidate_symbols_sha256=_digest_value(
            payload.get("candidate_symbols_sha256"), "candidate_symbols_sha256"
        ),
        prompt_sha256=_digest_value(payload.get("prompt_sha256"), "prompt_sha256"),
        numeric_ranking_sha256=_digest_value(
            payload.get("numeric_ranking_sha256"), "numeric_ranking_sha256"
        ),
        candidate_observation_date=_optional_string(
            payload.get("candidate_observation_date"), "candidate_observation_date"
        ),
        candidate_generated_at=_optional_string(
            payload.get("candidate_generated_at"), "candidate_generated_at"
        ),
        decision_policy=cast(dict[str, object], policy),
    )


def write_shadow_launch_receipt(
    decision_plan: ShadowDecisionPlan | str | Path,
    output_dir: str | Path,
    *,
    provider: ShadowLaunchProvider,
    model: str,
    max_output_tokens: int = 8_192,
    thinking: ThinkingMode = "disabled",
    reasoning_effort: ReasoningEffort | None = None,
    issued_at: datetime | None = None,
) -> Path:
    """Write one provider/model launch receipt bound to a decision digest."""

    decision = _decision_plan_value(decision_plan)
    parameters = _model_parameters(
        provider=provider,
        model=model,
        max_output_tokens=max_output_tokens,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    created = issued_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("shadow launch receipt issued_at must include a UTC offset")
    core: dict[str, object] = {
        "schema_version": SHADOW_LAUNCH_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "ai_shadow_launch_receipt",
        "decision_plan_sha256": decision.decision_plan_sha256,
        "campaign_id": decision.campaign_id,
        "signal_date": decision.signal_date.isoformat(),
        "arm": decision.arm,
        "input_sha256": decision.input_sha256,
        "candidate_symbols_sha256": decision.candidate_symbols_sha256,
        "prompt_sha256": decision.prompt_sha256,
        "provider": provider,
        "model_parameters": parameters,
        "model_partition": f"{provider}--{model}",
        "issued_at": created.astimezone(timezone.utc).isoformat(),
    }
    payload = _content_addressed_payload(core)
    root = _reserve_directory(output_dir, "shadow launch receipt")
    path = root / "launch-receipt.json"
    _write_exclusive(path, _json_bytes(payload))
    load_shadow_launch_receipt(path)
    return path


def load_shadow_launch_receipt(path: str | Path) -> ShadowLaunchReceipt:
    """Load and strictly validate one provider-specific launch receipt."""

    artifact_path, artifact_bytes, payload = _read_artifact(
        path, "launch-receipt.json", "shadow launch receipt"
    )
    expected_keys = {
        "schema_version",
        "artifact_type",
        "decision_plan_sha256",
        "campaign_id",
        "signal_date",
        "arm",
        "input_sha256",
        "candidate_symbols_sha256",
        "prompt_sha256",
        "provider",
        "model_parameters",
        "model_partition",
        "issued_at",
        "content_sha256",
    }
    if set(payload) != expected_keys:
        raise ValueError("shadow launch receipt fields are invalid")
    if (
        payload.get("schema_version") != SHADOW_LAUNCH_RECEIPT_SCHEMA_VERSION
        or payload.get("artifact_type") != "ai_shadow_launch_receipt"
    ):
        raise ValueError("shadow launch receipt contract is invalid")
    content_sha256 = _validate_content_sha256(payload, "shadow launch receipt")
    provider = _provider(payload.get("provider"))
    parameters = payload.get("model_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("shadow launch receipt model_parameters is invalid")
    typed_parameters = cast(dict[str, object], parameters)
    _validate_model_parameters(provider, typed_parameters)
    model = cast(str, typed_parameters["model"])
    partition = payload.get("model_partition")
    if partition != f"{provider}--{model}":
        raise ValueError("shadow launch receipt model_partition is invalid")
    return ShadowLaunchReceipt(
        path=artifact_path,
        artifact_bytes=artifact_bytes,
        launch_receipt_sha256=content_sha256,
        decision_plan_sha256=_digest_value(
            payload.get("decision_plan_sha256"), "decision_plan_sha256"
        ),
        campaign_id=_identifier(payload.get("campaign_id"), "campaign_id"),
        signal_date=_date_value(payload.get("signal_date"), "signal_date"),
        arm=_arm(payload.get("arm")),
        input_sha256=_digest_value(payload.get("input_sha256"), "input_sha256"),
        candidate_symbols_sha256=_digest_value(
            payload.get("candidate_symbols_sha256"), "candidate_symbols_sha256"
        ),
        prompt_sha256=_digest_value(payload.get("prompt_sha256"), "prompt_sha256"),
        provider=provider,
        model_parameters=typed_parameters,
        model_partition=cast(str, partition),
        issued_at=_datetime_value(payload.get("issued_at"), "issued_at"),
    )


def validate_shadow_decision_plan(
    plan: SelectionPlan,
    decision_plan: ShadowDecisionPlan,
    *,
    campaign_id: str,
    signal_date: date,
) -> None:
    """Bind a decision artifact to the rebuilt owner candidate and prompt."""

    expected = _decision_plan_core(
        plan,
        campaign_id=campaign_id,
        signal_date=signal_date,
        require_frozen=False,
    )
    actual = json.loads(decision_plan.artifact_bytes)
    if not isinstance(actual, dict):
        raise ValueError("shadow decision plan must contain a JSON object")
    actual_core = dict(actual)
    actual_core.pop("content_sha256", None)
    if actual_core != expected:
        raise ValueError("shadow decision plan does not match the owner plan")


def validate_shadow_launch_receipt(
    decision_plan: ShadowDecisionPlan,
    launch_receipt: ShadowLaunchReceipt,
) -> None:
    """Bind provider/model authorization to the exact decision artifact."""

    expected = {
        "decision_plan_sha256": decision_plan.decision_plan_sha256,
        "campaign_id": decision_plan.campaign_id,
        "signal_date": decision_plan.signal_date,
        "arm": decision_plan.arm,
        "input_sha256": decision_plan.input_sha256,
        "candidate_symbols_sha256": decision_plan.candidate_symbols_sha256,
        "prompt_sha256": decision_plan.prompt_sha256,
    }
    actual = {
        "decision_plan_sha256": launch_receipt.decision_plan_sha256,
        "campaign_id": launch_receipt.campaign_id,
        "signal_date": launch_receipt.signal_date,
        "arm": launch_receipt.arm,
        "input_sha256": launch_receipt.input_sha256,
        "candidate_symbols_sha256": launch_receipt.candidate_symbols_sha256,
        "prompt_sha256": launch_receipt.prompt_sha256,
    }
    if actual != expected:
        raise ValueError("shadow launch receipt does not match the decision plan")


def canonical_content_sha256(payload: Mapping[str, object]) -> str:
    """Hash normalized JSON content, excluding the self-referential digest."""

    core = dict(payload)
    core.pop("content_sha256", None)
    return sha256(_canonical_json_bytes(core)).hexdigest()


def _decision_plan_core(
    plan: SelectionPlan,
    *,
    campaign_id: str,
    signal_date: date,
    require_frozen: bool = True,
) -> dict[str, object]:
    if plan.market != "CN" or plan.prompt_profile not in {
        "bounded_ranking_v3",
        "risk_veto_v1",
    }:
        raise ValueError("shadow decision plan requires a CN Prompt .8 plan")
    if require_frozen and (
        plan.plan_sha256 is None or _SHA256.fullmatch(plan.plan_sha256) is None
    ):
        raise ValueError("shadow decision plan requires a frozen owner plan")
    campaign = _identifier(campaign_id, "campaign_id")
    if plan.campaign_id is not None and plan.campaign_id != campaign:
        raise ValueError("shadow campaign_id differs from the frozen owner plan")
    if signal_date != plan.universe.selection_as_of:
        raise ValueError("shadow signal_date differs from the owner plan")
    read_plan_candidate_snapshot(plan)
    observation = plan.universe.observation_date
    generated = plan.universe.source_generated_at
    return {
        "schema_version": SHADOW_DECISION_PLAN_SCHEMA_VERSION,
        "artifact_type": "ai_shadow_decision_plan",
        "market": "CN",
        "campaign_id": campaign,
        "signal_date": signal_date.isoformat(),
        "arm": shadow_arm_for_profile(plan.prompt_profile),
        "prompt_profile": plan.prompt_profile,
        "prompt_version": plan.prompt_version,
        "style": plan.style,
        "top_n": plan.top_n,
        "input_contract": plan.universe.input_contract,
        "input_sha256": plan.universe.input_sha256,
        "candidate_symbols_sha256": plan.universe.candidate_symbols_sha256,
        "prompt_sha256": sha256(plan.prompt.encode()).hexdigest(),
        "numeric_ranking_sha256": sha256(numeric_ranking_bytes(plan)).hexdigest(),
        "candidate_observation_date": (
            observation.isoformat() if observation is not None else None
        ),
        "candidate_generated_at": (
            generated.astimezone(timezone.utc).isoformat()
            if generated is not None
            else None
        ),
        "repetitions": SHADOW_REPETITIONS,
        "min_valid_repetitions": SHADOW_MIN_VALID_REPETITIONS,
        "strict_point_in_time": False,
        "research_only": True,
        "decision_policy": plan.decision_policy_fields,
    }


def _decision_plan_value(
    value: ShadowDecisionPlan | str | Path,
) -> ShadowDecisionPlan:
    return (
        value
        if isinstance(value, ShadowDecisionPlan)
        else load_shadow_decision_plan(value)
    )


def _content_addressed_payload(core: Mapping[str, object]) -> dict[str, object]:
    payload = dict(core)
    payload["content_sha256"] = canonical_content_sha256(payload)
    return payload


def _validate_content_sha256(payload: Mapping[str, object], label: str) -> str:
    supplied = _digest_value(payload.get("content_sha256"), "content_sha256")
    if supplied != canonical_content_sha256(payload):
        raise ValueError(f"{label} canonical content hash is invalid")
    return supplied


def _model_parameters(
    *,
    provider: ShadowLaunchProvider,
    model: str,
    max_output_tokens: int,
    thinking: ThinkingMode,
    reasoning_effort: ReasoningEffort | None,
) -> dict[str, object]:
    if provider not in {"deepseek", "openai"}:
        raise ValueError("shadow launch receipt provider is invalid")
    parameters: dict[str, object] = {
        "provider": provider,
        "model": model,
        "max_output_tokens": max_output_tokens,
        "thinking": thinking if provider == "deepseek" else None,
        "reasoning_effort": reasoning_effort if provider == "deepseek" else None,
    }
    _validate_model_parameters(provider, parameters)
    return parameters


def _validate_model_parameters(
    provider: ShadowLaunchProvider, parameters: Mapping[str, object]
) -> None:
    if set(parameters) != {
        "provider",
        "model",
        "max_output_tokens",
        "thinking",
        "reasoning_effort",
    }:
        raise ValueError("shadow launch receipt model_parameters fields are invalid")
    model = parameters.get("model")
    maximum = parameters.get("max_output_tokens")
    if (
        parameters.get("provider") != provider
        or not isinstance(model, str)
        or _MODEL.fullmatch(model) is None
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not 1 <= maximum <= 65_536
    ):
        raise ValueError("shadow launch receipt model_parameters are invalid")
    thinking = parameters.get("thinking")
    effort = parameters.get("reasoning_effort")
    if provider == "openai" and (thinking is not None or effort is not None):
        raise ValueError("OpenAI launch receipt contains DeepSeek parameters")
    if provider == "deepseek" and (
        thinking not in {"enabled", "disabled"}
        or (thinking == "enabled" and effort not in {"high", "max"})
        or (thinking == "disabled" and effort is not None)
    ):
        raise ValueError("DeepSeek launch receipt reasoning parameters are invalid")


def _read_artifact(
    value: str | Path, expected_name: str, label: str
) -> tuple[Path, bytes, dict[str, object]]:
    supplied = Path(value).expanduser()
    if supplied.is_dir():
        supplied /= expected_name
    reject_symlink_path(supplied, label=label)
    path = supplied.resolve()
    if path.name != expected_name or not path.is_file():
        raise ValueError(f"{label} must end in a regular {expected_name}")
    try:
        artifact_bytes = path.read_bytes()
        payload = json.loads(artifact_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return path, artifact_bytes, cast(dict[str, object], payload)


def _reserve_directory(value: str | Path, label: str) -> Path:
    root = Path(value).expanduser().resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing overwrite of {label}: {root}") from exc
    return root


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"shadow {field} is invalid")
    return value


def _provider(value: object) -> ShadowLaunchProvider:
    if value not in {"deepseek", "openai"}:
        raise ValueError("shadow launch receipt provider is invalid")
    return cast(ShadowLaunchProvider, value)


def _arm(value: object) -> ShadowArm:
    if value not in {"bounded_ranking", "risk_veto"}:
        raise ValueError("shadow arm is invalid")
    return cast(ShadowArm, value)


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"shadow {field} is invalid")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field)


def _digest_value(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"shadow {field} is invalid")
    return value


def _date_value(value: object, field: str) -> date:
    text = _nonempty_string(value, field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"shadow {field} is not canonical")
    return parsed


def _datetime_value(value: object, field: str) -> datetime:
    text = _nonempty_string(value, field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"shadow {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"shadow {field} must include a UTC offset")
    if parsed.astimezone(timezone.utc).isoformat() != text:
        raise ValueError(f"shadow {field} must be canonical UTC")
    return parsed


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


__all__ = [
    "EvidenceStatus",
    "SHADOW_DECISION_PLAN_SCHEMA_VERSION",
    "SHADOW_LAUNCH_RECEIPT_SCHEMA_VERSION",
    "ShadowDecisionPlan",
    "ShadowLaunchBinding",
    "ShadowLaunchProvider",
    "ShadowLaunchReceipt",
    "ShadowModel",
    "ShadowProvider",
    "canonical_content_sha256",
    "load_shadow_decision_plan",
    "load_shadow_launch_receipt",
    "resolve_shadow_launch_binding",
    "validate_shadow_decision_plan",
    "validate_shadow_launch_receipt",
    "validate_shadow_launch_time",
    "write_shadow_decision_plan",
    "write_shadow_launch_receipt",
]
