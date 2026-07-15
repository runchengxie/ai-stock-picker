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
    validate_selection_artifact,
)


def response(*symbols: str, language: str = "en") -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 9 - index,
                    "reasoning": (
                        "综合候选评分支持该股票的相对排序。"
                        if language == "zh"
                        else (
                            "The overall candidate score supports the relative ranking."
                        )
                    ),
                    "risk_note": (
                        "风险说明仅基于综合候选评分，仍有信息边界。"
                        if language == "zh"
                        else (
                            "The overall candidate score is the only supplied basis "
                            "for this risk note."
                        )
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
    with pytest.raises(ValueError, match="Simplified Chinese"):
        create_selection(
            plan,
            response("600000.SH", language="en"),
            generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        )


def test_commentary_rejects_metadata_and_trade_advice(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    payload = json.loads(response("AAPL"))
    payload["picks"][0]["reasoning"] = (
        "The overall candidate score supports the ranking by DeepSeek."
    )
    with pytest.raises(ValueError, match="system metadata"):
        create_selection(plan, json.dumps(payload))
    payload = json.loads(response("AAPL"))
    payload["picks"][0]["risk_note"] = (
        "The overall candidate score supports buying this stock."
    )
    with pytest.raises(ValueError, match="trading advice"):
        create_selection(plan, json.dumps(payload))


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


def test_provider_output_json_fences_and_size_are_bounded(us_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    fenced = f"```json\n{response('AAPL')}\n```"
    artifact = create_selection(
        plan,
        fenced,
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    assert artifact.picks[0].symbol == "AAPL"
    with pytest.raises(ValueError, match="malformed markdown fences"):
        create_selection(plan, "```json\n{}")
    with pytest.raises(ValueError, match="1 MB"):
        create_selection(plan, "x" * 1_000_001)


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


def test_temporal_status_uses_market_timezone(
    cn_manifest: Path,
    us_manifest: Path,
) -> None:
    cn_plan = build_selection_plan(
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="zh-CN",
        provider="gemini",
    )
    cn_artifact = create_selection(
        cn_plan,
        response("600000.SH", language="zh"),
        generated_at=datetime(2026, 7, 15, 16, 30, tzinfo=timezone.utc),
    )
    assert cn_artifact.temporal_status == "retrospective_simulation"

    us_plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    us_artifact = create_selection(
        us_plan,
        response("AAPL"),
        generated_at=datetime(2026, 7, 16, 0, 30, tzinfo=timezone.utc),
    )
    assert us_artifact.temporal_status == "contemporaneous"


def test_artifact_schema_recomputes_temporal_status(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="zh-CN",
        provider="gemini",
    )
    artifact = create_selection(
        plan,
        response("600000.SH", language="zh"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump()
    payload["generated_at"] = datetime(2026, 7, 15, 16, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="market timezone"):
        SelectionArtifact.model_validate(payload)


def test_artifact_schema_enforces_hot_eod_cutoff(hot_manifest: Path) -> None:
    plan = build_selection_plan(
        candidates_path=hot_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="zh-CN",
        provider="gemini",
    )
    artifact = create_selection(
        plan,
        response("600000.SH", language="zh"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump()
    payload["candidate_generated_at"] = datetime(2026, 7, 14, 7, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="completed EOD cutoff"):
        SelectionArtifact.model_validate(payload)


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


def test_run_selection_passes_only_requested_credential_file_key(
    us_manifest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    credential_file = tmp_path / "owner.env"
    credential_file.write_text(
        "GEMINI_API_KEY=must-not-be-used\nDEEPSEEK_API_KEY=owner-key\n",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)
    observed: list[str | None] = []

    def fake_provider(
        prompt: str,
        provider: object,
        *,
        temperature: float,
        timeout: float,
        api_key: str | None,
    ) -> str:
        del prompt, provider, temperature, timeout
        observed.append(api_key)
        return response("AAPL")

    monkeypatch.setattr("ai_stock_picker.selection.call_provider", fake_provider)
    artifact = run_selection(
        plan,
        credential_file=credential_file,
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    assert artifact.picks[0].symbol == "AAPL"
    assert observed == ["owner-key"]


def test_artifact_revalidation_is_full(us_manifest: Path) -> None:
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
    result = validate_selection_artifact(artifact, us_manifest)
    assert result.validation_profile == "current_full"
    payload = artifact.model_dump()
    payload["generation_trace"]["prompt_sha256"] = "0" * 64
    tampered = SelectionArtifact.model_validate(payload)
    with pytest.raises(ValueError, match="prompt_sha256"):
        validate_selection_artifact(tampered, us_manifest)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("input_hash", "input_sha256"),
        ("membership", "outside candidate manifest"),
        ("enrichment", "enrichment does not match"),
        ("url", "URL, address, or secret"),
        ("trading", "trading advice"),
        ("provider", "system metadata"),
        ("language", "must use English"),
    ],
)
def test_artifact_revalidation_rejects_candidate_or_commentary_mutations(
    us_manifest: Path,
    case: str,
    message: str,
) -> None:
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
    payload = artifact.model_dump()
    if case == "input_hash":
        payload["generation_trace"]["input_sha256"] = "0" * 64
    elif case == "membership":
        payload["picks"][0]["symbol"] = "TSLA"
    elif case == "enrichment":
        payload["picks"][0]["name"] = "Invented Corp."
    elif case == "url":
        payload["picks"][0]["reasoning"] = (
            "The overall candidate score is detailed at https://example.com."
        )
    elif case == "trading":
        payload["picks"][0]["reasoning"] = (
            "The overall candidate score supports buying this stock."
        )
    elif case == "provider":
        payload["picks"][0]["reasoning"] = (
            "The overall candidate score was produced by DeepSeek."
        )
    else:
        payload["picks"][0]["reasoning"] = "综合候选评分支持该股票排序。"
    tampered = SelectionArtifact.model_validate(payload)
    with pytest.raises(ValueError, match=message):
        validate_selection_artifact(tampered, us_manifest)


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
