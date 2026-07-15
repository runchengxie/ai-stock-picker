from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_stock_picker.contracts import PROMPT_VERSION, SelectionArtifact
from ai_stock_picker.selection import (
    build_selection_plan,
    create_selection,
    run_selection,
)


def response(*symbols: str, language: str = "en") -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 9 - index,
                    "reasoning": (
                        f"候选特征支持 {symbol} 的排序"
                        if language == "zh"
                        else f"Evidence for {symbol}"
                    ),
                    "risk_note": (
                        f"{symbol} 的主要风险来自候选特征波动"
                        if language == "zh"
                        else f"Risk for {symbol}"
                    ),
                }
                for index, symbol in enumerate(symbols)
            ]
        },
        ensure_ascii=False,
    )


def test_plan_is_provider_neutral_across_markets(
    us_manifest: Path, cn_manifest: Path
) -> None:
    us_deepseek = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="growth",
        response_language="en",
        provider="deepseek",
    )
    cn_gemini = build_selection_plan(
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="zh-CN",
        provider="gemini",
    )
    assert us_deepseek.universe.market == "US"
    assert us_deepseek.provider.name == "deepseek"
    assert cn_gemini.universe.market == "CN"
    assert cn_gemini.provider.name == "gemini"
    assert json.loads(cn_gemini.prompt)["response_language"] == "zh-CN"


def test_custom_provider_plan_records_explicit_api(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="openai-compatible",
        model="custom-model",
        base_url="https://example.com/v1/chat/completions",
        api_key_env="CUSTOM_KEY",
    )
    assert plan.provider.provider_api == "openai-chat-completions-v1"
    assert plan.provider.model == "custom-model"


def test_selection_artifact_uses_generation_trace(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    artifact = create_selection(
        plan,
        response("AAPL", "MSFT"),
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    assert artifact.schema_version == "2.0.0"
    assert artifact.prompt_version == PROMPT_VERSION
    assert artifact.provider == "deepseek"
    assert artifact.market == "US"
    assert artifact.generation_trace.candidate_source == "us.json"
    assert "/" not in artifact.generation_trace.candidate_source
    assert artifact.picks[0].name == "Apple Inc."


def test_cn_output_language_is_independent_of_provider(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="momentum",
        response_language="zh-CN",
        provider="gemini",
    )
    artifact = create_selection(
        plan,
        response("600000.SH", language="zh"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    assert artifact.provider == "gemini"
    assert artifact.response_language == "zh-CN"
    with pytest.raises(ValueError, match="CJK"):
        create_selection(
            plan,
            response("600000.SH", language="en"),
            generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        )


def test_provider_output_must_match_candidate_set(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="quality",
        response_language="en",
        provider="gemini",
    )
    with pytest.raises(ValueError, match="exactly top_n"):
        create_selection(plan, response("AAPL"))
    with pytest.raises(ValueError, match="duplicate"):
        create_selection(plan, response("AAPL", "AAPL"))
    with pytest.raises(ValueError, match="outside candidate"):
        create_selection(plan, response("AAPL", "TSLA"))
    with pytest.raises(ValueError, match="strict schema"):
        create_selection(plan, "not-json")


def test_strict_schema_rejects_extra_fields_and_float(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="gemini",
    )
    payload = json.loads(response("AAPL"))
    payload["picks"][0]["name"] = "model supplied"
    with pytest.raises(ValueError, match="extra_forbidden"):
        create_selection(plan, json.dumps(payload))
    float_payload = response("AAPL").replace(
        '"confidence_score": 9', '"confidence_score": 9.0'
    )
    with pytest.raises(ValueError, match="int_type"):
        create_selection(plan, float_payload)


def test_temporal_status_and_causal_order(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    late = create_selection(
        plan,
        response("AAPL"),
        generated_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    assert late.temporal_status == "retrospective_simulation"
    assert "selection_generated_after_as_of" in late.evidence_limitations
    with pytest.raises(ValueError, match="manifest was generated after"):
        create_selection(
            plan,
            response("AAPL"),
            generated_at=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
        )


def test_run_selection_accepts_injected_provider(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    observed: list[tuple[str, str, float, float]] = []

    def caller(
        prompt: str, provider: object, temperature: float, timeout: float
    ) -> str:
        observed.append((prompt, plan.provider.model, temperature, timeout))
        return response("AAPL")

    artifact = run_selection(
        plan,
        timeout=3.5,
        caller=caller,
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    assert artifact.picks[0].symbol == "AAPL"
    assert observed == [(plan.prompt, "deepseek-chat", 0.2, 3.5)]


def test_artifact_round_trip_is_strict(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    artifact = create_selection(
        plan,
        response("AAPL"),
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    loaded = SelectionArtifact.model_validate_json(
        artifact.model_dump_json(), strict=True
    )
    assert loaded == artifact
