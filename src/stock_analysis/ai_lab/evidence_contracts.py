"""Layered transport, ranking, and publication evidence outcomes."""

from __future__ import annotations

import json
from datetime import datetime

from .providers import ProviderExchange
from .selection import SelectionPlan, create_selection, ranking_symbols


def selection_contracts(
    plan: SelectionPlan,
    exchange: ProviderExchange,
    *,
    generated_at: datetime,
) -> tuple[dict[str, str], bytes | None]:
    """Evaluate transport, ranking, and publication as separate contracts."""

    if exchange.response_text is None:
        return (
            {
                "transport_contract": "failed",
                "ranking_contract": "not_evaluated",
                "publication_contract": "not_evaluated",
            },
            None,
        )
    try:
        symbols = ranking_symbols(plan, exchange.response_text)
    except ValueError:
        return (
            {
                "transport_contract": "passed",
                "ranking_contract": "failed",
                "publication_contract": "not_evaluated",
            },
            None,
        )
    try:
        create_selection(plan, exchange.response_text, generated_at=generated_at)
    except ValueError:
        return (
            {
                "transport_contract": "passed",
                "ranking_contract": "passed",
                "publication_contract": "failed",
            },
            _ranking_diagnostic_bytes(symbols),
        )
    contracts = {
        "transport_contract": "passed",
        "ranking_contract": "passed",
        "publication_contract": "passed",
    }
    diagnostic = None
    return contracts, diagnostic


def _ranking_diagnostic_bytes(symbols: tuple[str, ...]) -> bytes:
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "ai_ranking_diagnostic",
        "symbols": list(symbols),
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


__all__ = ["selection_contracts"]
