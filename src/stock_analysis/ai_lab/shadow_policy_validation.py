"""Validate archived bounded-ranking and risk-veto policy partitions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .ranking_policy_contract import (
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V3_POLICY,
    RISK_VETO_POLICY,
)


def bounded_policy_partitions(
    manifest: Mapping[str, object],
) -> tuple[tuple[str, ...], frozenset[str]]:
    policy = manifest.get("ranking_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow ranking_policy is invalid")
    contract = (
        BOUNDED_RANKING_V2_POLICY
        if manifest.get("prompt_profile") == "bounded_ranking_v2"
        else BOUNDED_RANKING_V3_POLICY
    )
    static = contract.contract_record()
    if any(policy.get(field) != value for field, value in static.items()):
        raise ValueError("shadow ranking_policy static contract is invalid")
    expected_keys = {
        *static,
        "numeric_ranking_method",
        "locked_prefix_symbols",
        "boundary_symbols",
    }
    if set(policy) != expected_keys:
        raise ValueError("shadow ranking_policy fields are invalid")
    locked = policy.get("locked_prefix_symbols")
    boundary = policy.get("boundary_symbols")
    if (
        not isinstance(locked, list)
        or len(locked) != contract.locked_prefix_count
        or not isinstance(boundary, list)
        or len(boundary)
        != contract.boundary_end_rank - contract.boundary_start_rank + 1
        or any(not isinstance(item, str) or not item for item in [*locked, *boundary])
        or len({*locked, *boundary}) != len(locked) + len(boundary)
    ):
        raise ValueError("shadow ranking_policy partitions are invalid")
    return tuple(cast(list[str], locked)), frozenset(cast(list[str], boundary))


def risk_policy_partitions(
    manifest: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    policy = manifest.get("risk_veto_policy")
    if not isinstance(policy, dict):
        raise ValueError("shadow risk_veto_policy is invalid")
    static = RISK_VETO_POLICY.contract_record()
    if any(policy.get(field) != value for field, value in static.items()):
        raise ValueError("shadow risk_veto_policy static contract is invalid")
    expected_keys = {
        *static,
        "numeric_ranking_method",
        "selected_symbols",
        "reserve_symbols",
    }
    if set(policy) != expected_keys:
        raise ValueError("shadow risk_veto_policy fields are invalid")
    selected = policy.get("selected_symbols")
    reserves = policy.get("reserve_symbols")
    if (
        not isinstance(selected, list)
        or len(selected) != RISK_VETO_POLICY.selected_count
        or not isinstance(reserves, list)
        or len(reserves)
        != RISK_VETO_POLICY.reserve_end_rank - RISK_VETO_POLICY.reserve_start_rank + 1
        or any(not isinstance(item, str) or not item for item in [*selected, *reserves])
        or len({*selected, *reserves}) != len(selected) + len(reserves)
    ):
        raise ValueError("shadow risk_veto_policy partitions are invalid")
    return tuple(cast(list[str], selected)), tuple(cast(list[str], reserves))


__all__ = ["bounded_policy_partitions", "risk_policy_partitions"]
