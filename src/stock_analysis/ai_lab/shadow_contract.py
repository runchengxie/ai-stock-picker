"""Versioned arm, response, and consensus rules for research shadow runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import median
from typing import Literal, cast

from .contracts import (
    LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION,
    SHADOW_CAMPAIGN_SCHEMA_VERSION,
    RankingModelSelection,
    RiskCode,
    RiskVetoModelDecision,
)
from .ranking_policy import policy_partitions, risk_veto_partitions
from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V3_POLICY,
    RISK_VETO_POLICY,
)
from .risk_veto import risk_veto_decision
from .selection import SelectionPlan, ranking_symbols

ShadowArm = Literal["bounded_ranking", "risk_veto"]
RiskDecision = tuple[str | None, RiskCode]


def shadow_arm_for_profile(profile: str) -> ShadowArm:
    """Resolve the immutable owner arm for a supported shadow profile."""

    if profile in {"bounded_ranking_v2", "bounded_ranking_v3"}:
        return "bounded_ranking"
    if profile == "risk_veto_v1":
        return "risk_veto"
    raise ValueError("unsupported shadow prompt profile")


def shadow_schema_for_profile(profile: str) -> str:
    """Keep .7 artifacts on their original schema while new arms use 1.1."""

    return (
        LEGACY_SHADOW_CAMPAIGN_SCHEMA_VERSION
        if profile == "bounded_ranking_v2"
        else SHADOW_CAMPAIGN_SCHEMA_VERSION
    )


def shadow_response_schema(plan: SelectionPlan) -> dict[str, object]:
    """Return the exact strict provider response schema for one owner plan."""

    if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto":
        return RiskVetoModelDecision.model_json_schema()
    return RankingModelSelection.model_json_schema()


def shadow_response_schema_name(plan: SelectionPlan) -> str:
    """Return the stable OpenAI Structured Outputs schema name."""

    return (
        "ai_stock_risk_veto"
        if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto"
        else "ai_stock_ranking"
    )


def parse_shadow_response(
    plan: SelectionPlan, response_text: str
) -> tuple[str, tuple[str, ...] | RiskDecision]:
    """Apply the same strict local response contract to every provider."""

    if shadow_arm_for_profile(plan.prompt_profile) == "risk_veto":
        return "risk_veto", risk_veto_decision(plan, response_text)
    return "bounded_ranking", ranking_symbols(plan, response_text)


def risk_decision_payload(decision: RiskDecision) -> dict[str, object]:
    """Serialize one canonical risk-veto repetition diagnostic."""

    symbol, risk_code = decision
    return {
        "schema_version": "1.0.0",
        "artifact_type": "ai_risk_veto_diagnostic",
        "veto_symbol": symbol or "NONE",
        "risk_code": risk_code,
    }


def bounded_consensus_payload(
    plan: SelectionPlan,
    valid: Sequence[tuple[int, tuple[str, ...]]],
) -> dict[str, object] | None:
    """Build legacy .7 Borda or strict .8 majority consensus."""

    policy = (
        BOUNDED_RANKING_V2_POLICY
        if plan.prompt_profile == "bounded_ranking_v2"
        else BOUNDED_RANKING_V3_POLICY
    )
    locked, _boundary = policy_partitions(plan.universe, policy)
    records = _bounded_tallies(valid, len(locked))
    if plan.prompt_profile == "bounded_ranking_v2":
        winners = [cast(str, item["symbol"]) for item in records[:3]]
        method = "votes_then_borda_then_median_then_symbol_v1"
    else:
        majority = [item for item in records if cast(int, item["votes"]) >= 2]
        if len(majority) < policy.boundary_selection_count:
            return None
        winners = [
            cast(str, item["symbol"])
            for item in majority[: policy.boundary_selection_count]
        ]
        method = "two_of_three_votes_then_borda_then_median_then_symbol_v2"
    return {
        "schema_version": shadow_schema_for_profile(plan.prompt_profile),
        "artifact_type": "ai_shadow_consensus_ranking",
        "method": method,
        "valid_repetitions": [item[0] for item in valid],
        "locked_prefix": list(locked),
        "boundary_winners": winners,
        "selected_symbols": [*locked, *winners],
        "boundary_tallies": records,
    }


def risk_veto_consensus_payload(
    plan: SelectionPlan,
    valid: Sequence[tuple[int, RiskDecision]],
) -> dict[str, object] | None:
    """Require an exact 2/3 decision and apply deterministic Numeric replacement."""

    tallies: dict[RiskDecision, int] = {}
    for _repetition, decision in valid:
        tallies[decision] = tallies.get(decision, 0) + 1
    records: list[dict[str, object]] = [
        {
            "veto_symbol": decision[0] or "NONE",
            "risk_code": decision[1],
            "votes": votes,
        }
        for decision, votes in tallies.items()
    ]
    records.sort(
        key=lambda item: (
            -cast(int, item["votes"]),
            cast(str, item["veto_symbol"]),
            cast(str, item["risk_code"]),
        )
    )
    if not records or cast(int, records[0]["votes"]) < 2:
        return None
    winner = records[0]
    veto_value = cast(str, winner["veto_symbol"])
    veto_symbol = None if veto_value == "NONE" else veto_value
    selected, reserves = risk_veto_partitions(plan.universe, RISK_VETO_POLICY)
    effective = list(selected)
    replacement: str | None = None
    if veto_symbol is not None:
        effective.remove(veto_symbol)
        replacement = next(symbol for symbol in reserves if symbol not in effective)
        effective.append(replacement)
    return {
        "schema_version": SHADOW_CAMPAIGN_SCHEMA_VERSION,
        "artifact_type": "ai_shadow_consensus_risk_veto",
        "method": "exact_decision_two_of_three_then_numeric_replacement_v1",
        "valid_repetitions": [item[0] for item in valid],
        "veto_symbol": veto_symbol or "NONE",
        "risk_code": winner["risk_code"],
        "replacement_symbol": replacement,
        "numeric_selection_symbols": list(selected),
        "selected_symbols": effective,
        "decision_tallies": records,
    }


def read_risk_decision(payload: Mapping[str, object]) -> RiskDecision:
    """Validate and normalize one archived risk-veto diagnostic payload."""

    decision = RiskVetoModelDecision.model_validate(
        {
            "veto_symbol": payload.get("veto_symbol"),
            "risk_code": payload.get("risk_code"),
        },
        strict=True,
    )
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("artifact_type") != "ai_risk_veto_diagnostic"
    ):
        raise ValueError("shadow risk-veto diagnostic contract is invalid")
    return (
        None if decision.veto_symbol == "NONE" else decision.veto_symbol,
        decision.risk_code,
    )


def _bounded_tallies(
    valid: Sequence[tuple[int, tuple[str, ...]]], locked_count: int
) -> list[dict[str, object]]:
    tallies: dict[str, dict[str, object]] = {}
    locked = valid[0][1][:locked_count]
    for _repetition, symbols in valid:
        if symbols[:locked_count] != locked:
            raise ValueError("valid repetitions disagree on the locked Numeric prefix")
        for order, symbol in enumerate(symbols[locked_count:], start=1):
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


__all__ = [
    "RiskDecision",
    "ShadowArm",
    "bounded_consensus_payload",
    "parse_shadow_response",
    "read_risk_decision",
    "risk_decision_payload",
    "risk_veto_consensus_payload",
    "shadow_arm_for_profile",
    "shadow_response_schema",
    "shadow_response_schema_name",
    "shadow_schema_for_profile",
]
