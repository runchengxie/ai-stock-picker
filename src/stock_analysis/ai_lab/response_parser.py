"""Strict provider-response parsing shared by selection profiles."""

from __future__ import annotations

from typing import TypeVar

from pydantic import ValidationError

from .contracts import ModelSelection, RankingModelSelection, RiskVetoModelDecision

_MAX_RESPONSE_BYTES = 1_000_000
_ModelT = TypeVar(
    "_ModelT", ModelSelection, RankingModelSelection, RiskVetoModelDecision
)


def parse_response(response_text: str) -> ModelSelection:
    """Parse the publication-compatible legacy response contract."""

    return _parse_model(response_text, ModelSelection)


def parse_ranking_response(response_text: str) -> RankingModelSelection:
    """Parse a strict ranking-only response with no commentary fields."""

    return _parse_model(response_text, RankingModelSelection)


def parse_risk_veto_response(response_text: str) -> RiskVetoModelDecision:
    """Parse the strict one-veto response contract."""

    return _parse_model(response_text, RiskVetoModelDecision)


def _parse_model(response_text: str, model: type[_ModelT]) -> _ModelT:
    if len(response_text.encode()) > _MAX_RESPONSE_BYTES:
        raise ValueError("provider output exceeds the 1 MB safety limit")
    text = response_text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[len("```json\n") : -len("\n```")].strip()
    elif "```" in text:
        raise ValueError("provider output contains malformed markdown fences")
    try:
        return model.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise ValueError(f"provider output violates the strict schema: {exc}") from exc


__all__ = ["parse_ranking_response", "parse_response", "parse_risk_veto_response"]
