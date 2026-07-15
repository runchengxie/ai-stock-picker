from __future__ import annotations

import pytest

from ai_stock_picker.candidate_models import Candidate
from ai_stock_picker.commentary_validation import validate_customer_commentary


@pytest.fixture
def candidate() -> Candidate:
    return Candidate(
        symbol="AAPL",
        name="Apple Inc.",
        topic="Technology",
        score=9.0,
        features={
            "trend_score": 0.8,
            "intraday_stability_score": 0.7,
            "sector": "Technology",
        },
    )


def validate(value: str, candidate: Candidate, field: str = "reasoning") -> None:
    validate_customer_commentary(
        field,
        value,
        candidate,
        market="US",
        provider="deepseek",
        model="deepseek-chat",
    )


def test_accepts_grounded_commentary(candidate: Candidate) -> None:
    validate("The overall candidate score supports the relative ranking.", candidate)
    validate(
        "The candidate topic Technology is the supplied basis for this note.",
        candidate,
    )


def test_requires_actual_categorical_value(candidate: Candidate) -> None:
    with pytest.raises(ValueError, match="supplied candidate value"):
        validate("The candidate topic supports the ranking.", candidate)


def test_rejects_unsupported_field(candidate: Candidate) -> None:
    with pytest.raises(ValueError, match="unsupported candidate field"):
        validate("The earnings_growth_score supports the ranking.", candidate)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            "The overall candidate score supports a buy recommendation.",
            "trading advice",
        ),
        (
            "According to analysts, the overall candidate score supports the ranking.",
            "external or future claim",
        ),
        (
            "The overall candidate score supports the ranking at https://example.com.",
            "URL, address, or secret",
        ),
        (
            "The overall candidate score supports the ranking by DeepSeek.",
            "system metadata",
        ),
        (
            "The overall candidate score does not support the ranking.",
            "negates",
        ),
    ],
)
def test_rejects_forbidden_customer_content(
    candidate: Candidate, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate(value, candidate)


def test_stability_semantics_cannot_be_reversed(candidate: Candidate) -> None:
    with pytest.raises(ValueError, match="stability semantics"):
        validate(
            "Higher intraday stability means higher risk for this candidate.",
            candidate,
        )


def test_chinese_locale_can_be_used_for_any_market(candidate: Candidate) -> None:
    validate_customer_commentary(
        "reasoning",
        "综合候选评分支持该股票的相对排序。",
        candidate,
        market="CN",
        provider="gemini",
        model="gemini-2.5-flash",
    )
