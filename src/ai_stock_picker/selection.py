"""Build plans, validate model output, and create selection artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .candidate_models import Candidate, CandidateUniverse
from .candidates import load_candidate_universe
from .commentary_validation import validate_customer_commentary
from .contracts import (
    GenerationTrace,
    Market,
    ModelSelection,
    ResponseLanguage,
    SelectionArtifact,
    StockPick,
    Style,
    TEMPERATURE,
    TemporalStatus,
    validate_symbol,
)
from .credentials import load_api_key
from .prompting import build_prompt
from .providers import (
    ProviderConfig,
    ProviderKind,
    call_provider,
    resolve_provider_config,
)

ProviderCaller = Callable[[str, ProviderConfig, float, float], str]

_MAX_PROMPT_BYTES = 2_000_000
_MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class SelectionPlan:
    """A validated provider request before network access."""

    universe: CandidateUniverse
    provider: ProviderConfig
    style: Style
    response_language: ResponseLanguage
    top_n: int
    temperature: float
    prompt: str


@dataclass(frozen=True, slots=True)
class SelectionValidationResult:
    """Audit profile applied while revalidating a persisted artifact."""

    validation_profile: str
    prompt_hash_revalidated: bool
    commentary_policy_revalidated: bool


def build_selection_plan(
    *,
    candidates_path: str | Path,
    as_of: date,
    top_n: int,
    style: Style,
    response_language: ResponseLanguage,
    provider: ProviderKind,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    temperature: float = TEMPERATURE,
) -> SelectionPlan:
    """Validate input and build a deterministic, provider-neutral plan."""

    if top_n < 1:
        raise ValueError("top_n must be positive")
    universe = load_candidate_universe(candidates_path, as_of=as_of)
    if top_n > len(universe.candidates):
        raise ValueError(
            f"top_n={top_n} exceeds candidate count={len(universe.candidates)}"
        )
    provider_config = resolve_provider_config(
        provider, model=model, base_url=base_url, api_key_env=api_key_env
    )
    prompt = build_prompt(
        universe,
        style=style,
        top_n=top_n,
        response_language=response_language,
    )
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ValueError("generated prompt exceeds the 2 MB safety limit")
    return SelectionPlan(
        universe=universe,
        provider=provider_config,
        style=style,
        response_language=response_language,
        top_n=top_n,
        temperature=temperature,
        prompt=prompt,
    )


def create_selection(
    plan: SelectionPlan,
    response_text: str,
    *,
    generated_at: datetime | None = None,
) -> SelectionArtifact:
    """Validate model JSON and enrich it from the candidate manifest."""

    model_selection = _parse_response(response_text)
    if len(model_selection.picks) != plan.top_n:
        raise ValueError("provider output must contain exactly top_n picks")
    candidate_map = {
        candidate.symbol: candidate for candidate in plan.universe.candidates
    }
    symbols: list[str] = []
    picks: list[StockPick] = []
    for rank, model_pick in enumerate(model_selection.picks, 1):
        symbol = validate_symbol(model_pick.symbol, plan.universe.market)
        if symbol in symbols:
            raise ValueError(f"provider output contains duplicate symbol: {symbol}")
        candidate = candidate_map.get(symbol)
        if candidate is None:
            raise ValueError(
                f"provider output symbol is outside candidate pool: {symbol}"
            )
        reasoning = model_pick.reasoning.strip()
        risk_note = model_pick.risk_note.strip()
        _validate_pick_commentary(plan, candidate, reasoning, risk_note)
        symbols.append(symbol)
        picks.append(
            StockPick(
                rank=rank,
                symbol=symbol,
                name=candidate.name,
                topic=candidate.topic,
                confidence_score=model_pick.confidence_score,
                reasoning=reasoning,
                risk_note=risk_note,
            )
        )

    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("generated_at must include a UTC offset")
    market_timezone = ZoneInfo(
        "Asia/Shanghai" if plan.universe.market == "CN" else "America/New_York"
    )
    created_market_date = created.astimezone(market_timezone).date()
    if created_market_date < plan.universe.selection_as_of:
        raise ValueError("generated_at precedes the selection as_of date")
    if plan.universe.source_generated_at > created:
        raise ValueError("candidate manifest was generated after the selection")
    temporal_status: TemporalStatus = "contemporaneous"
    limitations = list(plan.universe.evidence_limitations)
    if created_market_date > plan.universe.selection_as_of:
        temporal_status = "retrospective_simulation"
        limitations.append("selection_generated_after_as_of")
    return SelectionArtifact(
        market=plan.universe.market,
        response_language=plan.response_language,
        selection_as_of=plan.universe.selection_as_of,
        candidate_observation_date=plan.universe.observation_date,
        candidate_generated_at=plan.universe.source_generated_at.astimezone(
            timezone.utc
        ),
        data_cutoff=plan.universe.data_cutoff,
        upstream_execution_not_before=plan.universe.upstream_execution_not_before,
        generated_at=created.astimezone(timezone.utc),
        provider=plan.provider.name,
        provider_api=plan.provider.provider_api,
        model=plan.provider.model,
        temperature=plan.temperature,
        style=plan.style,
        input_contract=plan.universe.input_contract,
        temporal_status=temporal_status,
        point_in_time_assurance=plan.universe.point_in_time_assurance,
        evidence_limitations=tuple(dict.fromkeys(limitations)),
        input_count=len(plan.universe.candidates),
        requested_top_n=plan.top_n,
        generation_trace=GenerationTrace(
            candidate_source=plan.universe.source_name,
            input_sha256=plan.universe.input_sha256,
            candidate_symbols_sha256=plan.universe.candidate_symbols_sha256,
            prompt_sha256=sha256(plan.prompt.encode()).hexdigest(),
            response_sha256=sha256(response_text.encode()).hexdigest(),
        ),
        picks=tuple(picks),
    )


def _validate_pick_commentary(
    plan: SelectionPlan,
    candidate: Candidate,
    reasoning: str,
    risk_note: str,
) -> None:
    commentary_locale: Market = (
        "CN" if plan.response_language == "zh-CN" else "US"
    )
    for field, value in (("reasoning", reasoning), ("risk_note", risk_note)):
        validate_customer_commentary(
            field,
            value,
            candidate,
            market=commentary_locale,
            provider=plan.provider.name,
            model=plan.provider.model,
        )


def run_selection(
    plan: SelectionPlan,
    *,
    timeout: float = 120.0,
    caller: ProviderCaller | None = None,
    generated_at: datetime | None = None,
    credential_file: str | Path | None = None,
) -> SelectionArtifact:
    """Call the configured provider and return a validated artifact."""

    if caller is not None:
        response = caller(plan.prompt, plan.provider, plan.temperature, timeout)
    else:
        api_key = (
            load_api_key(plan.provider.api_key_env, credential_file)
            if credential_file is not None
            else None
        )
        response = call_provider(
            plan.prompt,
            plan.provider,
            temperature=plan.temperature,
            timeout=timeout,
            api_key=api_key,
        )
    return create_selection(plan, response, generated_at=generated_at)


def validate_selection_artifact(
    artifact: SelectionArtifact,
    candidates_path: str | Path,
) -> SelectionValidationResult:
    """Fully revalidate a v2 artifact against its candidate manifest."""

    provider = _provider_kind(artifact.provider)
    base_url: str | None = None
    api_key_env: str | None = None
    if provider == "openai-compatible":
        base_url = "https://validation.invalid/v1/chat/completions"
        api_key_env = "VALIDATION_API_KEY"
    plan = build_selection_plan(
        candidates_path=candidates_path,
        as_of=artifact.selection_as_of,
        top_n=artifact.requested_top_n,
        style=artifact.style,
        response_language=artifact.response_language,
        provider=provider,
        model=artifact.model,
        base_url=base_url,
        api_key_env=api_key_env,
        temperature=artifact.temperature,
    )
    _validate_artifact_trace(artifact, plan)
    _validate_artifact_picks(artifact, plan)
    return SelectionValidationResult(
        validation_profile="current_full",
        prompt_hash_revalidated=True,
        commentary_policy_revalidated=True,
    )


def _validate_artifact_trace(
    artifact: SelectionArtifact,
    plan: SelectionPlan,
) -> None:
    universe = plan.universe
    expected: dict[str, object] = {
        "candidate_source": universe.source_name,
        "input_sha256": universe.input_sha256,
        "candidate_symbols_sha256": universe.candidate_symbols_sha256,
        "prompt_sha256": sha256(plan.prompt.encode()).hexdigest(),
        "candidate_observation_date": universe.observation_date,
        "candidate_generated_at": universe.source_generated_at.astimezone(timezone.utc),
        "data_cutoff": universe.data_cutoff,
        "upstream_execution_not_before": universe.upstream_execution_not_before,
        "input_contract": universe.input_contract,
        "point_in_time_assurance": universe.point_in_time_assurance,
        "input_count": len(universe.candidates),
        "market": universe.market,
        "provider_api": plan.provider.provider_api,
    }
    trace = artifact.generation_trace
    actual: dict[str, object] = {
        "candidate_source": trace.candidate_source,
        "input_sha256": trace.input_sha256,
        "candidate_symbols_sha256": trace.candidate_symbols_sha256,
        "prompt_sha256": trace.prompt_sha256,
        "candidate_observation_date": artifact.candidate_observation_date,
        "candidate_generated_at": artifact.candidate_generated_at,
        "data_cutoff": artifact.data_cutoff,
        "upstream_execution_not_before": artifact.upstream_execution_not_before,
        "input_contract": artifact.input_contract,
        "point_in_time_assurance": artifact.point_in_time_assurance,
        "input_count": artifact.input_count,
        "market": artifact.market,
        "provider_api": artifact.provider_api,
    }
    for field, expected_value in expected.items():
        if actual[field] != expected_value:
            raise ValueError(f"selection {field} does not match candidate manifest")
    expected_limitations = list(universe.evidence_limitations)
    if artifact.temporal_status == "retrospective_simulation":
        expected_limitations.append("selection_generated_after_as_of")
    if artifact.evidence_limitations != tuple(dict.fromkeys(expected_limitations)):
        raise ValueError(
            "selection evidence_limitations do not match candidate manifest"
        )


def _validate_artifact_picks(
    artifact: SelectionArtifact,
    plan: SelectionPlan,
) -> None:
    candidates = {item.symbol: item for item in plan.universe.candidates}
    for pick in artifact.picks:
        candidate = candidates.get(pick.symbol)
        if candidate is None:
            raise ValueError(
                f"selection symbol is outside candidate manifest: {pick.symbol}"
            )
        if pick.name != candidate.name or pick.topic != candidate.topic:
            raise ValueError(
                f"selection enrichment does not match candidate: {pick.symbol}"
            )
        _validate_pick_commentary(
            plan,
            candidate,
            pick.reasoning,
            pick.risk_note,
        )


def _provider_kind(value: str) -> ProviderKind:
    if value not in {"deepseek", "gemini", "openai-compatible"}:
        raise ValueError(f"unsupported selection provider: {value}")
    return cast(ProviderKind, value)


def _parse_response(response_text: str) -> ModelSelection:
    if len(response_text.encode()) > _MAX_RESPONSE_BYTES:
        raise ValueError("provider output exceeds the 1 MB safety limit")
    text = response_text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[len("```json\n") : -len("\n```")].strip()
    elif "```" in text:
        raise ValueError("provider output contains malformed markdown fences")
    try:
        return ModelSelection.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise ValueError(f"provider output violates the strict schema: {exc}") from exc


__all__ = [
    "ProviderCaller",
    "SelectionPlan",
    "SelectionValidationResult",
    "build_selection_plan",
    "create_selection",
    "run_selection",
    "validate_selection_artifact",
]
