"""Strict local validation for the narrow risk-veto response contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import RiskCode, validate_symbol
from .ranking_policy import risk_veto_partitions
from .response_parser import parse_risk_veto_response

if TYPE_CHECKING:
    from .selection import SelectionPlan


def risk_veto_decision(
    plan: SelectionPlan, response_text: str
) -> tuple[str | None, RiskCode]:
    """Validate one strict risk-veto response against the frozen Numeric Top10."""

    policy = plan.risk_veto_policy
    if policy is None:
        raise ValueError("risk-veto decision requires a risk_veto_v1 plan")
    decision = parse_risk_veto_response(response_text)
    if decision.veto_symbol == "NONE":
        return None, decision.risk_code
    symbol = validate_symbol(decision.veto_symbol, plan.market)
    selected, _reserves = risk_veto_partitions(plan.universe, policy)
    if symbol not in selected:
        raise ValueError("risk-veto symbol is outside the frozen Numeric Top10")
    return symbol, decision.risk_code


__all__ = ["risk_veto_decision"]
