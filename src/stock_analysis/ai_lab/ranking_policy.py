"""Deterministic Numeric ranking and bounded-output enforcement."""

from __future__ import annotations

import math
from collections.abc import Sequence
from hashlib import sha256

from .candidates import Candidate, CandidateUniverse
from .ranking_policy_contract import (
    BOUNDED_RANKING_POLICY,
    BOUNDED_RANKING_PROFILE,
    BoundedRankingPolicy,
)


def policy_for_profile(profile: str) -> BoundedRankingPolicy | None:
    """Resolve the opt-in policy; every existing profile remains unbounded."""

    return BOUNDED_RANKING_POLICY if profile == BOUNDED_RANKING_PROFILE else None


def numeric_ranking_method(universe: CandidateUniverse) -> str:
    """Return the frozen Numeric ordering identity for a candidate contract."""

    return (
        "relevance_desc_score_desc_symbol_asc"
        if universe.input_contract == "hot_sector_candidate_universe_v1"
        else "score_desc_symbol_asc"
    )


def numeric_ranked_candidates(universe: CandidateUniverse) -> tuple[Candidate, ...]:
    """Build the deterministic baseline used by plans, evidence, and policy."""

    if universe.input_contract == "hot_sector_candidate_universe_v1":
        relevance = {
            candidate.symbol: hot_sector_relevance(candidate)
            for candidate in universe.candidates
        }
        return tuple(
            sorted(
                universe.candidates,
                key=lambda candidate: (
                    -relevance[candidate.symbol],
                    -candidate.score,
                    candidate.symbol,
                ),
            )
        )
    return tuple(
        sorted(
            universe.candidates,
            key=lambda candidate: (-candidate.score, candidate.symbol),
        )
    )


def validate_policy_plan(
    policy: BoundedRankingPolicy,
    universe: CandidateUniverse,
    *,
    market: str,
    top_n: int,
) -> None:
    """Reject any plan that cannot implement the immutable bounded policy."""

    if market != "CN":
        raise ValueError("bounded_ranking_v1 is restricted to the CN research path")
    if top_n != policy.required_output_count:
        raise ValueError(
            f"bounded_ranking_v1 requires top_n={policy.required_output_count}"
        )
    if len(universe.candidates) < policy.boundary_end_rank:
        raise ValueError(
            "bounded_ranking_v1 requires at least "
            f"{policy.boundary_end_rank} candidates"
        )


def blinded_presentation_order(
    universe: CandidateUniverse, policy: BoundedRankingPolicy
) -> tuple[str, ...]:
    """Hash-shuffle candidates without using or exposing their Numeric rank."""

    prefix = f"{policy.policy_id}\0{universe.input_sha256}\0"
    return tuple(
        sorted(
            (candidate.symbol for candidate in universe.candidates),
            key=lambda symbol: sha256(f"{prefix}{symbol}".encode()).hexdigest(),
        )
    )


def policy_partitions(
    universe: CandidateUniverse, policy: BoundedRankingPolicy
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the exact locked prefix and boundary membership."""

    ranked = numeric_ranked_candidates(universe)
    locked = tuple(
        candidate.symbol for candidate in ranked[: policy.locked_prefix_count]
    )
    boundary = tuple(
        candidate.symbol
        for candidate in ranked[
            policy.boundary_start_rank - 1 : policy.boundary_end_rank
        ]
    )
    return locked, boundary


def validate_policy_selection(
    universe: CandidateUniverse,
    policy: BoundedRankingPolicy,
    symbols: Sequence[str],
) -> None:
    """Enforce the lock and boundary independently of prompt compliance."""

    locked, boundary = policy_partitions(universe, policy)
    supplied = tuple(symbols)
    if supplied[: policy.locked_prefix_count] != locked:
        raise ValueError("bounded ranking output changed the locked Numeric prefix")
    tail = supplied[policy.locked_prefix_count :]
    if len(tail) != policy.boundary_selection_count:
        raise ValueError("bounded ranking output has the wrong boundary pick count")
    if not set(tail).issubset(boundary):
        raise ValueError("bounded ranking output contains a symbol outside ranks 8-15")


def policy_evidence_record(
    universe: CandidateUniverse, policy: BoundedRankingPolicy
) -> dict[str, object]:
    """Bind the static policy to the exact Numeric membership in one run."""

    locked, boundary = policy_partitions(universe, policy)
    return {
        **policy.contract_record(),
        "numeric_ranking_method": numeric_ranking_method(universe),
        "locked_prefix_symbols": list(locked),
        "boundary_symbols": list(boundary),
    }


def boundary_score_level(policy: BoundedRankingPolicy, numeric_rank: int) -> str:
    """Coarsen a boundary rank into a stable three-level representation."""

    relative = numeric_rank - policy.boundary_start_rank
    if relative < 0 or numeric_rank > policy.boundary_end_rank:
        raise ValueError("numeric rank is outside the bounded policy")
    if relative < 3:
        return "upper"
    if relative < 6:
        return "middle"
    return "lower"


def hot_sector_relevance(candidate: Candidate) -> float:
    value = candidate.features.get("relevance")
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise ValueError("hot-sector numeric ranking requires finite relevance")
    return float(value)


__all__ = [
    "blinded_presentation_order",
    "boundary_score_level",
    "hot_sector_relevance",
    "numeric_ranked_candidates",
    "numeric_ranking_method",
    "policy_evidence_record",
    "policy_for_profile",
    "policy_partitions",
    "validate_policy_plan",
    "validate_policy_selection",
]
