"""Resolve immutable research policies and deterministic presentation order."""

from __future__ import annotations

from collections.abc import Sequence

from .candidates import CandidateUniverse
from .contracts import Market, PromptProfile
from .prompting import presentation_order
from .ranking_policy import (
    blinded_presentation_order,
    policy_for_profile,
    risk_veto_policy_for_profile,
    risk_veto_presentation_order,
    validate_policy_plan,
    validate_risk_veto_plan,
)
from .ranking_policy_contract import BoundedRankingPolicy, RiskVetoPolicy


def research_plan(
    supplied: bool,
    ranking_policy: BoundedRankingPolicy | None,
    risk_veto_policy: RiskVetoPolicy | None,
) -> bool:
    return supplied or ranking_policy is not None or risk_veto_policy is not None


def policy_and_order(
    universe: CandidateUniverse,
    market: Market,
    top_n: int,
    prompt_profile: PromptProfile,
    supplied: Sequence[str] | None,
) -> tuple[
    BoundedRankingPolicy | None,
    RiskVetoPolicy | None,
    tuple[str, ...],
]:
    """Resolve one mutually exclusive policy and its presentation permutation."""

    policy = policy_for_profile(prompt_profile)
    risk_policy = risk_veto_policy_for_profile(prompt_profile)
    if policy is not None:
        validate_policy_plan(policy, universe, market=market, top_n=top_n)
        order = blinded_presentation_order(universe, policy)
        _require_owner_order(universe, market, supplied, order, "bounded ranking")
        return policy, None, order
    if risk_policy is not None:
        validate_risk_veto_plan(risk_policy, universe, market=market, top_n=top_n)
        order = risk_veto_presentation_order(universe, risk_policy)
        _require_owner_order(universe, market, supplied, order, "risk veto")
        return None, risk_policy, order
    return None, None, presentation_order(universe, market, supplied)


def _require_owner_order(
    universe: CandidateUniverse,
    market: Market,
    supplied: Sequence[str] | None,
    expected: tuple[str, ...],
    label: str,
) -> None:
    if (
        supplied is not None
        and presentation_order(universe, market, supplied) != expected
    ):
        raise ValueError(
            f"{label} requires its deterministic blinded presentation order"
        )


__all__ = ["policy_and_order", "research_plan"]
