"""Build prompts, validate provider output, and persist selection artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from .candidates import Candidate, CandidateUniverse, load_candidate_universe
from .commentary_validation import (
    validate_customer_commentary,
    validate_legacy_customer_commentary,
)
from .contracts import (
    LEGACY_STABILITY_PROMPT_VERSION,
    Lineage,
    Market,
    ModelSelection,
    PromptProfile,
    Provider,
    ReadablePromptVersion,
    SelectionArtifact,
    StockPick,
    Style,
    TemporalStatus,
    prompt_version_for_profile,
    validate_prompt_profile,
    validate_symbol,
)
from .credentials import load_provider_api_key
from .inference_config import inference_parameters as _inference_parameters
from .prompting import (
    build_prompt as _build_prompt,
)
from .prompting import (
    name_aliases as _name_aliases,
)
from .prompting import (
    presentation_order as _presentation_order,
)
from .prompting import (
    replace_universe_identities as _replace_universe_identities,
)
from .prompting import (
    symbol_aliases as _symbol_aliases,
)
from .prompting import (
    validate_identity_redaction as _validate_identity_redaction,
)
from .providers import (
    DEFAULT_DEEPSEEK_MAX_TOKENS,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_DEEPSEEK_THINKING,
    ProviderExchange,
    ProviderParameterSchema,
    ReasoningEffort,
    ThinkingMode,
    call_deepseek,
    call_deepseek_exchange,
    call_gemini,
    call_gemini_exchange,
    deepseek_provider_parameters,
)
from .ranking_policy import (
    blinded_presentation_order,
    policy_evidence_record,
    policy_for_profile,
    validate_policy_plan,
    validate_policy_selection,
)
from .ranking_policy_contract import BoundedRankingPolicy
from .response_parser import parse_response as _parse_response
from .selection_persistence import write_selection, write_stability_selection

_MAX_PROMPT_BYTES = 2_000_000
_DEFAULT_MODELS: dict[Market, str] = {
    "CN": DEFAULT_DEEPSEEK_MODEL,
    "US": "gemini-2.5-flash",
}
_DEFAULT_STYLES: dict[Market, Style] = {"CN": "momentum", "US": "quality"}
_MARKET_STYLES: dict[Market, frozenset[Style]] = {
    "CN": frozenset({"momentum", "quality"}),
    "US": frozenset({"quality", "growth"}),
}


@dataclass(frozen=True, slots=True)
class SelectionPlan:
    """A fully validated provider request before any network access."""

    universe: CandidateUniverse
    market: Market
    provider: Provider
    model: str
    provider_parameter_schema: ProviderParameterSchema
    source_candidate_path: str
    campaign_id: str | None
    trial_id: str | None
    plan_sha256: str | None
    research_only: bool
    thinking: ThinkingMode | None
    reasoning_effort: ReasoningEffort | None
    max_tokens: int | None
    style: Style
    top_n: int
    prompt: str
    prompt_version: ReadablePromptVersion
    prompt_profile: PromptProfile
    ranking_policy: BoundedRankingPolicy | None
    presentation_order: tuple[str, ...]
    symbol_aliases: tuple[tuple[str, str], ...]
    name_aliases: tuple[tuple[str, str], ...]

    @property
    def ranking_policy_record(self) -> dict[str, object] | None:
        """Return the exact run-bound policy record, when explicitly enabled."""

        if self.ranking_policy is None:
            return None
        return policy_evidence_record(self.universe, self.ranking_policy)

    @property
    def ranking_policy_fields(self) -> dict[str, object]:
        """Return optional manifest fields without changing existing profiles."""

        record = self.ranking_policy_record
        return {"ranking_policy": record} if record is not None else {}


@dataclass(frozen=True, slots=True)
class SelectionValidationResult:
    validation_profile: str
    prompt_hash_revalidated: bool
    commentary_policy_revalidated: bool


def build_selection_plan(
    *,
    market: Market,
    candidates_path: str | Path,
    as_of: date,
    top_n: int,
    style: Style | None = None,
    model: str | None = None,
    thinking: ThinkingMode | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    max_tokens: int | None = None,
    provider_parameter_schema: ProviderParameterSchema = "explicit_v2",
    presentation_order: Sequence[str] | None = None,
    symbol_aliases: Mapping[str, str] | None = None,
    name_aliases: Mapping[str, str] | None = None,
    prompt_profile: PromptProfile = "production_v4",
    source_candidate_path: str | None = None,
    campaign_id: str | None = None,
    trial_id: str | None = None,
    plan_sha256: str | None = None,
    research_only: bool = False,
) -> SelectionPlan:
    """Validate a candidate snapshot and build a deterministic prompt."""

    selected_style = _selected_style(market, style)
    if top_n < 1:
        raise ValueError("top_n must be positive")
    universe = load_candidate_universe(candidates_path, market=market, as_of=as_of)
    if top_n > len(universe.candidates):
        raise ValueError(
            f"top_n={top_n} exceeds candidate count={len(universe.candidates)}"
        )
    ranking_policy, order = _ranking_policy_and_order(
        universe, market, top_n, prompt_profile, presentation_order
    )
    provider: Provider = "deepseek" if market == "CN" else "gemini"
    selected_model, source_path = _selection_metadata(
        market=market,
        model=model,
        prompt_profile=prompt_profile,
        source_candidate_path=source_candidate_path,
        universe_path=universe.path,
        plan_sha256=plan_sha256,
    )
    selected_thinking, selected_effort, selected_max_tokens = _inference_parameters(
        provider,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        parameter_schema=provider_parameter_schema,
    )
    aliases = _symbol_aliases(universe, market, symbol_aliases)
    names = _name_aliases(universe, market, name_aliases)
    prompt_version = prompt_version_for_profile(prompt_profile)
    prompt = _build_prompt(
        universe,
        market,
        selected_style,
        top_n,
        presentation_order=order,
        symbol_aliases=dict(aliases),
        name_aliases=dict(names),
        include_legacy_example=prompt_profile == "legacy_stability_v3",
        ranking_only=prompt_profile == "ranking_only_v1",
        bounded_policy=ranking_policy,
    )
    if aliases and names:
        _validate_identity_redaction(
            prompt,
            ((candidate.symbol, candidate.name) for candidate in universe.candidates),
        )
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ValueError("generated prompt exceeds the 2 MB safety limit")
    return SelectionPlan(
        universe=universe,
        market=market,
        provider=provider,
        model=selected_model,
        provider_parameter_schema=provider_parameter_schema,
        source_candidate_path=source_path,
        campaign_id=campaign_id,
        trial_id=trial_id,
        plan_sha256=plan_sha256,
        research_only=research_only or ranking_policy is not None,
        thinking=selected_thinking,
        reasoning_effort=selected_effort,
        max_tokens=selected_max_tokens,
        style=selected_style,
        top_n=top_n,
        prompt=prompt,
        prompt_version=prompt_version,
        prompt_profile=prompt_profile,
        ranking_policy=ranking_policy,
        presentation_order=order,
        symbol_aliases=aliases,
        name_aliases=names,
    )


def _ranking_policy_and_order(
    universe: CandidateUniverse,
    market: Market,
    top_n: int,
    prompt_profile: PromptProfile,
    supplied: Sequence[str] | None,
) -> tuple[BoundedRankingPolicy | None, tuple[str, ...]]:
    policy = policy_for_profile(prompt_profile)
    if policy is None:
        return None, _presentation_order(universe, market, supplied)
    validate_policy_plan(policy, universe, market=market, top_n=top_n)
    order = blinded_presentation_order(universe, policy)
    if (
        supplied is not None
        and _presentation_order(universe, market, supplied) != order
    ):
        raise ValueError(
            "bounded ranking requires its deterministic blinded presentation order"
        )
    return policy, order


def _selected_style(market: Market, style: Style | None) -> Style:
    selected = style or _DEFAULT_STYLES[market]
    if selected not in _MARKET_STYLES[market]:
        allowed = ", ".join(sorted(_MARKET_STYLES[market]))
        raise ValueError(f"style {selected!r} is invalid for {market}; use {allowed}")
    return selected


def _selection_metadata(
    *,
    market: Market,
    model: str | None,
    prompt_profile: PromptProfile,
    source_candidate_path: str | None,
    universe_path: Path,
    plan_sha256: str | None,
) -> tuple[str, str]:
    selected_model = (model or _DEFAULT_MODELS[market]).strip()
    if not selected_model:
        raise ValueError("model must not be empty")
    validate_prompt_profile(prompt_profile)
    source_path = source_candidate_path or str(universe_path)
    if not Path(source_path).is_absolute():
        raise ValueError("source_candidate_path must be absolute")
    if plan_sha256 is not None and (
        len(plan_sha256) != 64
        or any(character not in "0123456789abcdef" for character in plan_sha256)
    ):
        raise ValueError("plan_sha256 must be a lowercase SHA-256 digest")
    return selected_model, source_path


def _selection_limitations(plan: SelectionPlan) -> list[str]:
    limitations = list(plan.universe.evidence_limitations)
    if plan.ranking_policy is not None:
        limitations.append(plan.ranking_policy.selection_limitation)
    return limitations


def create_selection(
    plan: SelectionPlan,
    response_text: str,
    *,
    generated_at: datetime | None = None,
) -> SelectionArtifact:
    """Validate strict model JSON and enrich it from canonical candidates."""

    model_selection = _parse_response(response_text)
    if len(model_selection.picks) != plan.top_n:
        raise ValueError("provider output must contain exactly top_n picks")

    picks = _create_picks(plan, model_selection)
    if plan.ranking_policy is not None:
        validate_policy_selection(
            plan.universe,
            plan.ranking_policy,
            tuple(pick.symbol for pick in picks),
        )

    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        raise ValueError("generated_at must include a UTC offset")
    market_timezone = ZoneInfo(
        "Asia/Shanghai" if plan.market == "CN" else "America/New_York"
    )
    temporal_status: TemporalStatus = "contemporaneous"
    limitations = _selection_limitations(plan)
    created_market_date = created.astimezone(market_timezone).date()
    if created_market_date < plan.universe.selection_as_of:
        raise ValueError("generated_at precedes the selection as_of date")
    if (
        plan.universe.source_generated_at is not None
        and plan.universe.source_generated_at > created
    ):
        raise ValueError("candidate manifest was generated after the selection")
    if created_market_date > plan.universe.selection_as_of:
        temporal_status = "retrospective_simulation"
        limitations.append("selection_generated_after_as_of")
    prompt_hash = sha256(plan.prompt.encode()).hexdigest()
    response_hash = sha256(response_text.encode()).hexdigest()
    return SelectionArtifact(
        market=plan.market,
        selection_as_of=plan.universe.selection_as_of,
        candidate_observation_date=plan.universe.observation_date,
        candidate_generated_at=(
            plan.universe.source_generated_at.astimezone(timezone.utc)
            if plan.universe.source_generated_at is not None
            else None
        ),
        data_cutoff=plan.universe.data_cutoff,
        upstream_execution_not_before=plan.universe.upstream_execution_not_before,
        generated_at=created.astimezone(timezone.utc),
        provider=plan.provider,
        model=plan.model,
        prompt_version=plan.prompt_version,
        style=plan.style,
        input_contract=plan.universe.input_contract,
        temporal_status=temporal_status,
        point_in_time_assurance=plan.universe.point_in_time_assurance,
        strict_point_in_time=False,
        eligible_as_oos_evidence=False,
        evidence_limitations=tuple(dict.fromkeys(limitations)),
        input_count=len(plan.universe.candidates),
        requested_top_n=plan.top_n,
        lineage=Lineage(
            candidate_path=plan.source_candidate_path,
            input_sha256=plan.universe.input_sha256,
            candidate_symbols_sha256=plan.universe.candidate_symbols_sha256,
            prompt_sha256=prompt_hash,
            response_sha256=response_hash,
        ),
        picks=tuple(picks),
    )


def ranking_symbols(plan: SelectionPlan, response_text: str) -> tuple[str, ...]:
    """Validate the model's ranking without applying publication commentary rules."""

    model_selection = _parse_response(response_text)
    if len(model_selection.picks) != plan.top_n:
        raise ValueError("provider output must contain exactly top_n picks")
    candidates = {candidate.symbol for candidate in plan.universe.candidates}
    alias_map = {alias: symbol for symbol, alias in plan.symbol_aliases}
    symbols: list[str] = []
    for model_pick in model_selection.picks:
        supplied = model_pick.symbol.strip().upper()
        symbol = validate_symbol(alias_map.get(supplied, supplied), plan.market)
        if symbol in symbols:
            raise ValueError(f"provider output contains duplicate symbol: {symbol}")
        if symbol not in candidates:
            raise ValueError(
                f"provider output symbol is outside candidate pool: {symbol}"
            )
        symbols.append(symbol)
    result = tuple(symbols)
    if plan.ranking_policy is not None:
        validate_policy_selection(plan.universe, plan.ranking_policy, result)
    return result


def _create_picks(
    plan: SelectionPlan, model_selection: ModelSelection
) -> tuple[StockPick, ...]:
    candidates = {candidate.symbol: candidate for candidate in plan.universe.candidates}
    alias_map = {alias: symbol for symbol, alias in plan.symbol_aliases}
    symbol_aliases = dict(plan.symbol_aliases)
    name_aliases = dict(plan.name_aliases)
    symbols: list[str] = []
    picks: list[StockPick] = []
    for rank, model_pick in enumerate(model_selection.picks, 1):
        supplied_symbol = model_pick.symbol.strip().upper()
        symbol = validate_symbol(
            alias_map.get(supplied_symbol, supplied_symbol), plan.market
        )
        if symbol in symbols:
            raise ValueError(f"provider output contains duplicate symbol: {symbol}")
        candidate = candidates.get(symbol)
        if candidate is None:
            raise ValueError(
                f"provider output symbol is outside candidate pool: {symbol}"
            )
        reasoning = model_pick.reasoning.strip()
        risk_note = model_pick.risk_note.strip()
        displayed_symbol = symbol_aliases.get(symbol, candidate.symbol)
        displayed_name = name_aliases.get(symbol, candidate.name)
        commentary_candidate = Candidate(
            symbol=displayed_symbol,
            name=displayed_name,
            topic=cast(
                str,
                _replace_universe_identities(
                    candidate.topic,
                    plan.universe,
                    symbol_aliases=symbol_aliases,
                    name_aliases=name_aliases,
                ),
            ),
            score=candidate.score,
            features=cast(
                dict[str, object],
                _replace_universe_identities(
                    candidate.features,
                    plan.universe,
                    symbol_aliases=symbol_aliases,
                    name_aliases=name_aliases,
                ),
            ),
        )
        _validate_pick_commentary(plan, commentary_candidate, reasoning, risk_note)
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
    return tuple(picks)


def _validate_pick_commentary(
    plan: SelectionPlan,
    candidate: Candidate,
    reasoning: str,
    risk_note: str,
) -> None:
    for field, value in (("reasoning", reasoning), ("risk_note", risk_note)):
        validate_customer_commentary(
            field,
            value,
            candidate,
            market=plan.market,
            provider=plan.provider,
            model=plan.model,
        )


def run_selection(
    plan: SelectionPlan,
    *,
    timeout: float = 120,
    caller: Callable[[str, str, float], str] | None = None,
    generated_at: datetime | None = None,
    credential_file: str | Path | None = None,
) -> SelectionArtifact:
    """Call the plan's bound provider and return a validated artifact."""

    read_plan_candidate_snapshot(plan)
    response = (
        caller(
            plan.prompt,
            plan.model,
            timeout,
        )
        if caller is not None
        else call_plan_provider(
            plan,
            timeout=timeout,
            credential_file=credential_file,
        )
    )
    return create_selection(plan, response, generated_at=generated_at)


def read_plan_candidate_snapshot(plan: SelectionPlan) -> bytes:
    """Read the current candidate bytes and require the plan's frozen digest."""

    try:
        payload = plan.universe.path.read_bytes()
    except OSError as exc:
        raise ValueError("candidate input is unavailable after plan creation") from exc
    if sha256(payload).hexdigest() != plan.universe.input_sha256:
        raise ValueError("candidate input changed after selection plan creation")
    return payload


def validate_selection_artifact(
    artifact: SelectionArtifact,
    candidates_path: str | Path,
    *,
    presentation_order: Sequence[str] | None = None,
    symbol_aliases: Mapping[str, str] | None = None,
    name_aliases: Mapping[str, str] | None = None,
    prompt_profile: PromptProfile = "production_v4",
) -> SelectionValidationResult:
    """Revalidate a readable artifact against its canonical candidate snapshot."""

    plan = build_selection_plan(
        market=artifact.market,
        candidates_path=candidates_path,
        as_of=artifact.selection_as_of,
        top_n=artifact.requested_top_n,
        style=artifact.style,
        model=artifact.model,
        presentation_order=presentation_order,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
        prompt_profile=prompt_profile,
    )
    prompt_hash_revalidated = artifact.prompt_version == plan.prompt_version
    commentary_revalidated = (
        prompt_hash_revalidated and prompt_profile == "production_v4"
    )
    _validate_artifact_candidate_lineage(
        artifact,
        plan,
        prompt_hash_revalidated=prompt_hash_revalidated,
    )
    _validate_artifact_picks(
        artifact,
        plan,
        commentary_policy_revalidated=commentary_revalidated,
    )
    return SelectionValidationResult(
        validation_profile=(
            "current_full" if prompt_hash_revalidated else "legacy_read_only"
        ),
        prompt_hash_revalidated=prompt_hash_revalidated,
        commentary_policy_revalidated=commentary_revalidated,
    )


def _validate_artifact_candidate_lineage(
    artifact: SelectionArtifact,
    plan: SelectionPlan,
    *,
    prompt_hash_revalidated: bool,
) -> None:
    universe = plan.universe
    expected_generated_at = (
        universe.source_generated_at.astimezone(timezone.utc)
        if universe.source_generated_at is not None
        else None
    )
    expected: dict[str, object] = {
        "candidate_path": str(universe.path),
        "input_sha256": universe.input_sha256,
        "candidate_symbols_sha256": universe.candidate_symbols_sha256,
        "candidate_observation_date": universe.observation_date,
        "candidate_generated_at": expected_generated_at,
        "data_cutoff": universe.data_cutoff,
        "upstream_execution_not_before": universe.upstream_execution_not_before,
        "input_contract": universe.input_contract,
        "point_in_time_assurance": universe.point_in_time_assurance,
        "input_count": len(universe.candidates),
    }
    actual: dict[str, object] = {
        "candidate_path": artifact.lineage.candidate_path,
        "input_sha256": artifact.lineage.input_sha256,
        "candidate_symbols_sha256": artifact.lineage.candidate_symbols_sha256,
        "candidate_observation_date": artifact.candidate_observation_date,
        "candidate_generated_at": artifact.candidate_generated_at,
        "data_cutoff": artifact.data_cutoff,
        "upstream_execution_not_before": artifact.upstream_execution_not_before,
        "input_contract": artifact.input_contract,
        "point_in_time_assurance": artifact.point_in_time_assurance,
        "input_count": artifact.input_count,
    }
    if prompt_hash_revalidated:
        expected["prompt_sha256"] = sha256(plan.prompt.encode()).hexdigest()
        actual["prompt_sha256"] = artifact.lineage.prompt_sha256
    for field, expected_value in expected.items():
        if actual[field] != expected_value:
            raise ValueError(f"selection {field} does not match candidate snapshot")

    expected_limitations = _selection_limitations(plan)
    if artifact.temporal_status == "retrospective_simulation":
        expected_limitations.append("selection_generated_after_as_of")
    if artifact.evidence_limitations != tuple(dict.fromkeys(expected_limitations)):
        raise ValueError(
            "selection evidence_limitations do not match candidate snapshot"
        )


def _validate_artifact_picks(
    artifact: SelectionArtifact,
    plan: SelectionPlan,
    *,
    commentary_policy_revalidated: bool,
) -> None:
    candidates = {item.symbol: item for item in plan.universe.candidates}
    for pick in artifact.picks:
        candidate = candidates.get(pick.symbol)
        if candidate is None:
            raise ValueError(
                f"selection symbol is outside candidate snapshot: {pick.symbol}"
            )
        if pick.name != candidate.name or pick.topic != candidate.topic:
            raise ValueError(
                f"selection enrichment does not match candidate: {pick.symbol}"
            )
        if commentary_policy_revalidated:
            _validate_pick_commentary(
                plan,
                candidate,
                pick.reasoning,
                pick.risk_note,
            )
        else:
            _validate_legacy_pick_commentary(plan, pick.reasoning, pick.risk_note)
    if plan.ranking_policy is not None:
        validate_policy_selection(
            plan.universe,
            plan.ranking_policy,
            tuple(pick.symbol for pick in artifact.picks),
        )


def _validate_legacy_pick_commentary(
    plan: SelectionPlan,
    reasoning: str,
    risk_note: str,
) -> None:
    for field, value in (("reasoning", reasoning), ("risk_note", risk_note)):
        validate_legacy_customer_commentary(
            field,
            value,
            market=plan.market,
            provider=plan.provider,
            model=plan.model,
        )


def call_plan_provider(
    plan: SelectionPlan,
    *,
    timeout: float = 120,
    credential_file: str | Path | None = None,
) -> str:
    """Dispatch to the provider fixed by the plan's market."""

    read_plan_candidate_snapshot(plan)
    if credential_file is not None:
        api_key = load_provider_api_key(plan.provider, credential_file)
        if plan.provider == "deepseek":
            schema, thinking, effort, max_tokens = _plan_deepseek_parameters(plan)
            return call_deepseek(
                plan.prompt,
                model=plan.model,
                thinking=thinking,
                reasoning_effort=effort,
                max_tokens=max_tokens,
                parameter_schema=schema,
                timeout=timeout,
                api_key=api_key,
            )
        return call_gemini(
            plan.prompt,
            model=plan.model,
            timeout=timeout,
            api_key=api_key,
        )
    if plan.provider == "deepseek":
        schema, thinking, effort, max_tokens = _plan_deepseek_parameters(plan)
        return call_deepseek(
            plan.prompt,
            model=plan.model,
            thinking=thinking,
            reasoning_effort=effort,
            max_tokens=max_tokens,
            parameter_schema=schema,
            timeout=timeout,
        )
    return call_gemini(plan.prompt, model=plan.model, timeout=timeout)


def call_plan_provider_exchange(
    plan: SelectionPlan,
    *,
    timeout: float = 120,
    credential_file: str | Path | None = None,
) -> ProviderExchange:
    """Call the bound provider and retain its credential-free exchange."""

    read_plan_candidate_snapshot(plan)
    api_key = (
        load_provider_api_key(plan.provider, credential_file)
        if credential_file is not None
        else None
    )
    if plan.provider == "deepseek":
        schema, thinking, effort, max_tokens = _plan_deepseek_parameters(plan)
        return call_deepseek_exchange(
            plan.prompt,
            model=plan.model,
            thinking=thinking,
            reasoning_effort=effort,
            max_tokens=max_tokens,
            parameter_schema=schema,
            timeout=timeout,
            api_key=api_key,
        )
    return call_gemini_exchange(
        plan.prompt,
        model=plan.model,
        timeout=timeout,
        api_key=api_key,
    )


def _plan_deepseek_parameters(
    plan: SelectionPlan,
) -> tuple[ProviderParameterSchema, ThinkingMode, ReasoningEffort | None, int]:
    if plan.provider_parameter_schema == "legacy_v1":
        return (
            "legacy_v1",
            DEFAULT_DEEPSEEK_THINKING,
            None,
            DEFAULT_DEEPSEEK_MAX_TOKENS,
        )
    if plan.thinking is None or plan.max_tokens is None:
        raise ValueError("DeepSeek selection plan is missing inference parameters")
    deepseek_provider_parameters(
        thinking=plan.thinking,
        reasoning_effort=plan.reasoning_effort,
        max_tokens=plan.max_tokens,
    )
    return (
        plan.provider_parameter_schema,
        plan.thinking,
        plan.reasoning_effort,
        plan.max_tokens,
    )


__all__ = [
    "LEGACY_STABILITY_PROMPT_VERSION",
    "PromptProfile",
    "SelectionPlan",
    "SelectionValidationResult",
    "build_selection_plan",
    "call_plan_provider",
    "call_plan_provider_exchange",
    "create_selection",
    "read_plan_candidate_snapshot",
    "ranking_symbols",
    "run_selection",
    "validate_selection_artifact",
    "write_selection",
    "write_stability_selection",
]
