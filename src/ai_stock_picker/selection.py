"""Build plans, validate model output, and create selection artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .candidate_models import CandidateUniverse
from .candidates import load_candidate_universe
from .contracts import (
    GenerationTrace,
    ModelSelection,
    ResponseLanguage,
    SelectionArtifact,
    StockPick,
    Style,
    TEMPERATURE,
    TemporalStatus,
    validate_symbol,
)
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
_CJK_IDEOGRAPH = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


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
        if plan.response_language == "zh-CN":
            _require_cjk("reasoning", reasoning)
            _require_cjk("risk_note", risk_note)
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


def run_selection(
    plan: SelectionPlan,
    *,
    timeout: float = 120.0,
    caller: ProviderCaller | None = None,
    generated_at: datetime | None = None,
) -> SelectionArtifact:
    """Call the configured provider and return a validated artifact."""

    response = (
        caller(plan.prompt, plan.provider, plan.temperature, timeout)
        if caller is not None
        else call_provider(
            plan.prompt,
            plan.provider,
            temperature=plan.temperature,
            timeout=timeout,
        )
    )
    return create_selection(plan, response, generated_at=generated_at)


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


def _require_cjk(field: str, value: str) -> None:
    if _CJK_IDEOGRAPH.search(value) is None:
        raise ValueError(
            f"provider output {field} must contain at least one CJK ideograph"
        )


__all__ = [
    "ProviderCaller",
    "SelectionPlan",
    "build_selection_plan",
    "create_selection",
    "run_selection",
]
