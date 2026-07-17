"""Versioned contracts for explicitly bounded research ranking policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BOUNDED_RANKING_PROMPT_VERSION: Literal["2026-07-17.2"] = "2026-07-17.2"
BOUNDED_RANKING_PROFILE: Literal["bounded_ranking_v1"] = "bounded_ranking_v1"


@dataclass(frozen=True, slots=True)
class BoundedRankingPolicy:
    """Immutable Numeric-prefix and boundary-selection policy."""

    schema_version: str
    policy_id: str
    locked_prefix_count: int
    boundary_start_rank: int
    boundary_end_rank: int
    boundary_selection_count: int
    required_output_count: int
    score_representation: str
    hidden_exact_fields: tuple[str, ...]
    presentation_order_method: str
    selection_limitation: str

    def contract_record(self) -> dict[str, object]:
        """Return the static machine-readable policy contract."""

        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "locked_prefix_count": self.locked_prefix_count,
            "boundary_start_rank": self.boundary_start_rank,
            "boundary_end_rank": self.boundary_end_rank,
            "boundary_selection_count": self.boundary_selection_count,
            "required_output_count": self.required_output_count,
            "score_representation": self.score_representation,
            "hidden_exact_fields": list(self.hidden_exact_fields),
            "presentation_order_method": self.presentation_order_method,
        }


BOUNDED_RANKING_POLICY = BoundedRankingPolicy(
    schema_version="1.0.0",
    policy_id="numeric_top7_boundary8_15_select3_v1",
    locked_prefix_count=7,
    boundary_start_rank=8,
    boundary_end_rank=15,
    boundary_selection_count=3,
    required_output_count=10,
    score_representation="stable_boundary_level_v1",
    hidden_exact_fields=("score", "relevance"),
    presentation_order_method="sha256_input_policy_symbol_v1",
    selection_limitation="bounded_ranking_policy_v1_research_only",
)


__all__ = [
    "BOUNDED_RANKING_POLICY",
    "BOUNDED_RANKING_PROFILE",
    "BOUNDED_RANKING_PROMPT_VERSION",
    "BoundedRankingPolicy",
]
