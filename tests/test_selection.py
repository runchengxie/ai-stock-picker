from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from stock_analysis.ai_lab.contracts import PROMPT_VERSION, SelectionArtifact
from stock_analysis.ai_lab.selection import (
    build_selection_plan,
    call_plan_provider,
    create_selection,
    run_selection,
    write_selection,
)


def _response(*symbols: str, language: str = "zh") -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 9 - index,
                    "reasoning": (
                        f"依据综合候选评分对 {symbol} 进行相对排序"
                        if language == "zh"
                        else (
                            "The overall candidate score supports the relative rank "
                            f"for {symbol}"
                        )
                    ),
                    "risk_note": (
                        f"仅依据日内波动稳定性，{symbol} 的风险解读仍有信息边界"
                        if language == "zh"
                        else (
                            "The overall candidate score leaves uncertainty for "
                            f"{symbol}"
                        )
                    ),
                }
                for index, symbol in enumerate(symbols)
            ]
        }
    )


def test_cn_plan_binds_provider_style_and_candidate_hash(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="momentum",
    )
    body = json.loads(plan.prompt)
    assert plan.provider == "deepseek"
    assert plan.model == "deepseek-v4-flash"
    assert plan.thinking == "disabled"
    assert plan.reasoning_effort is None
    assert plan.max_tokens == 8192
    assert body["style"] == "momentum"
    assert body["required_count"] == 2
    assert body["selection_as_of"] == "2026-07-15"
    assert body["candidate_observation_date"] == "2026-07-14"
    assert [item["symbol"] for item in body["candidates"]] == [
        "600000.SH",
        "000001.SZ",
        "430047.BJ",
    ]
    assert "price/volume momentum" in body["style_guidance"]
    first_features = body["candidates"][0]["features"]
    assert first_features["intraday_stability_score"] == 0.85
    assert "risk_score" not in first_features
    assert "risk_score is projected into intraday_stability_score" in plan.prompt
    assert (
        "Higher means more stable"
        in body["feature_semantics"]["intraday_stability_score"]
    )
    assert body["commentary_field_labels"]["score"] == "综合候选评分"
    assert (
        body["commentary_field_labels"]["intraday_stability_score"] == "日内波动稳定性"
    )
    assert body["commentary_policy"] == {
        "kind": "ai_interpretation",
        "independent_fact_check": "not_performed",
        "customer_disclaimer": (
            "AI interpretation based only on supplied candidate fields; "
            "not independently fact-checked."
        ),
    }


def test_us_plan_uses_gemini_and_quality_default(us_manifest: Path) -> None:
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
    )
    assert plan.provider == "gemini"
    assert plan.model == "gemini-2.5-flash"
    assert plan.style == "quality"


def test_prompts_bind_market_specific_output_language(
    cn_manifest: Path, us_manifest: Path
) -> None:
    cn = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    us = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    cn_prompt = json.loads(cn.prompt)
    us_prompt = json.loads(us.prompt)
    assert cn_prompt["response_language"] == "Simplified Chinese"
    assert any("CJK ideograph" in item for item in cn_prompt["constraints"])
    assert "response_example" not in cn_prompt
    assert (
        cn_prompt["response_schema"]["picks"][0]["symbol"]
        == "one exact symbol supplied in candidates"
    )
    assert us_prompt["response_language"] == "English"
    assert "Write reasoning and risk_note in English." in us_prompt["constraints"]
    assert "response_example" not in us_prompt


def test_style_changes_prompt_materially(us_manifest: Path) -> None:
    quality = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="quality",
    )
    growth = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
        style="growth",
    )
    assert quality.prompt != growth.prompt
    assert "explicit supplied growth" in growth.prompt


@pytest.mark.parametrize(("market", "style"), [("CN", "growth"), ("US", "momentum")])
def test_market_rejects_inapplicable_style(
    cn_manifest: Path, market: str, style: str
) -> None:
    with pytest.raises(ValueError, match="invalid"):
        build_selection_plan(
            market=market,  # type: ignore[arg-type]
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            style=style,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("top_n", [0, 4])
def test_plan_rejects_invalid_top_n(cn_manifest: Path, top_n: int) -> None:
    with pytest.raises(ValueError, match="top_n"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=top_n,
        )


def test_plan_rejects_blank_model(cn_manifest: Path) -> None:
    with pytest.raises(ValueError, match="model"):
        build_selection_plan(
            market="CN",
            candidates_path=cn_manifest,
            as_of=date(2026, 7, 15),
            top_n=1,
            model=" ",
        )


def test_selection_enriches_only_from_candidates(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
    )
    created = datetime(2026, 7, 15, 2, tzinfo=timezone.utc)
    response = _response("000001.sz", "600000.SH")
    artifact = create_selection(plan, response, generated_at=created)
    assert artifact.selection_as_of == date(2026, 7, 15)
    assert artifact.candidate_observation_date == date(2026, 7, 14)
    assert artifact.candidate_generated_at == datetime(
        2026, 7, 14, 22, 0, tzinfo=timezone.utc
    )
    assert artifact.temporal_status == "contemporaneous"
    assert artifact.point_in_time_assurance == "signal_date_only"
    assert artifact.strict_point_in_time is False
    assert artifact.eligible_as_oos_evidence is False
    assert "rotation_publisher_receipt_unavailable" in artifact.evidence_limitations
    assert artifact.upstream_execution_not_before == "next_trading_session"
    assert artifact.generated_at == created
    assert artifact.provider == "deepseek"
    assert artifact.prompt_version == PROMPT_VERSION == "2026-07-17.6"
    assert artifact.input_count == 3
    assert artifact.requested_top_n == 2
    assert [pick.symbol for pick in artifact.picks] == ["000001.SZ", "600000.SH"]
    assert [pick.name for pick in artifact.picks] == ["平安银行", "浦发银行"]
    assert [pick.topic for pick in artifact.picks] == ["金融科技", "银行"]
    assert artifact.lineage.input_sha256 == plan.universe.input_sha256
    assert len(artifact.lineage.prompt_sha256) == 64
    assert len(artifact.lineage.response_sha256) == 64


def test_artifact_strictly_loads_previous_prompt_version(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    current = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    legacy_payload = current.model_dump()
    legacy_payload["prompt_version"] = "2026-07-15.2"

    loaded = SelectionArtifact.model_validate(legacy_payload, strict=True)

    assert loaded.prompt_version == "2026-07-15.2"
    assert current.prompt_version == PROMPT_VERSION == "2026-07-17.6"
    with pytest.raises(ValueError, match="current prompt version"):
        write_selection(loaded, cn_manifest.parent / "legacy-selection.json")
    assert not (cn_manifest.parent / "legacy-selection.json").exists()


@pytest.mark.parametrize("field", ["reasoning", "risk_note"])
def test_cn_selection_rejects_english_only_explanations(
    cn_manifest: Path, field: str
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    payload = json.loads(_response("600000.SH"))
    payload["picks"][0][field] = "English only model output"

    with pytest.raises(ValueError, match=rf"CN provider output {field}"):
        create_selection(plan, json.dumps(payload, ensure_ascii=False))


@pytest.mark.parametrize("field", ["reasoning", "risk_note"])
def test_commentary_must_cite_a_supplied_candidate_field(
    cn_manifest: Path, field: str
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    payload = json.loads(_response("600000.SH"))
    payload["picks"][0][field] = "这是一段没有候选字段依据的解读"

    with pytest.raises(ValueError, match="sentence without a supplied"):
        create_selection(plan, json.dumps(payload, ensure_ascii=False))


@pytest.mark.parametrize(
    "reasoning",
    [
        "综合候选评分支持相对排序。热点主题中的银行提供补充依据。",
        "score 支持相对排序。source_topics 中的银行提供补充依据。",
        "日内波动稳定性较高，表示候选字段中的日内表现更稳定。",
        "日内波动稳定性为0.85。",
        "股票代码600000.SH。",
    ],
)
def test_commentary_accepts_grounded_natural_aliases_and_exact_keys(
    cn_manifest: Path,
    reasoning: str,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    payload = json.loads(_response("600000.SH"))
    payload["picks"][0]["reasoning"] = reasoning

    artifact = create_selection(plan, json.dumps(payload, ensure_ascii=False))

    assert artifact.picks[0].reasoning == reasoning


@pytest.mark.parametrize(
    "reasoning",
    [
        "综合候选评分支持相对排序。第二句没有字段依据。",
        "综合候选评分支持相对排序.Second sentence has no field basis.",
    ],
)
def test_every_commentary_sentence_requires_its_own_grounding(
    cn_manifest: Path,
    reasoning: str,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    payload = json.loads(_response("600000.SH"))
    payload["picks"][0]["reasoning"] = reasoning

    with pytest.raises(ValueError, match="provider output reasoning"):
        create_selection(plan, json.dumps(payload, ensure_ascii=False))


@pytest.mark.parametrize(
    "commentary",
    [
        "依据综合候选评分，Ｄｅｅｐ　Ｓｅｅｋ 模型给出了这段解读。",
        "依据综合候选评分，DеepSeek 给出了这段解读。",
        "依据综合候选评分，α 模型给出了这段解读。",
        "依据综合候选评分，附带 provider id internal。",
        "依据综合候选评分，附带 model name internal。",
        "依据综合候选评分，附带 endpoint 元数据。",
        "依据综合候选评分，附带 prompt hash。",
        "依据综合候选评分，附带 response_sha256。",
        "依据综合候选评分，附带供应商标识 internal。",
        "依据综合候选评分，附带模型名称 internal。",
        "依据综合候选评分，由语言模型生成这段解读。",
        "依据综合候选评分，使用AI模型生成这段解读。",
        "依据综合候选评分，调用语言模型输出这段解读。",
        "综合候选评分由大模型生成。",
        "综合候选评分由模型生成。",
        "综合候选评分由LLM生成。",
        "依据综合候选评分，详情见 https://example.com/pick。",
        "依据综合候选评分，详情见 example.dev。",
        "依据综合候选评分，详情见example.tech/path。",
        "依据综合候选评分，详情见example．tech/path。",
        "依据综合候选评分，详情见 例子.测试。",
        "依据综合候选评分，详情见例子。测试。",
        "依据综合候选评分，联系 analyst@example.com。",
        "依据综合候选评分，详情见 192.168.1.10。",
        "依据综合候选评分，详情见 2001:db8::1。",
        "依据综合候选评分，API key 是 sk-abcdefghijk。",
        "依据综合候选评分，建议买入并设定目标价。",
        "依据综合候选评分，建议逢低布局并重仓配置。",
        "依据综合候选评分，建议择机布局并低吸。",
        "依据综合候选评分，适合长期持仓并纳入组合。",
        "依据综合候选评分，应当增配并提高仓位。",
        "依据热点主题，可以介入、参与并推荐该候选。",
        "依据综合候选评分，该结果可以保证收益。",
        "综合候选评分不能说明基本面，但公司产能和订单大增。",
        "依据热点主题，公告显示业绩、营收和利润增长。",
        "依据综合候选评分，政策将会推动公司盈利。",
        "依据综合候选评分，客户需求旺盛且竞争格局改善。",
        "综合候选评分并不支持该排序，结论仅依据主观直觉。",
        "综合候选评分并非排序依据，结论依据个人判断。",
        "综合候选评分与排序无关，结论依据个人判断。",
        "依据综合候选评分与 pe_ratio，候选排序较高。",
        "依据综合候选评分与 ret_5d，候选排序较高。",
        "依据综合候选评分，风险分也较高。",
        "日内波动稳定性为 0.85，该值越高代表风险越高。",
        "日内波动稳定性越高，代表波动越大。",
        "日内波动稳定性较低，因此风险低。",
        "日内波动稳定性越高，反而越不稳定。",
        "日内波动稳定性较低，却更稳定。",
    ],
)
def test_commentary_contract_rejects_unsafe_or_ungrounded_claims(
    cn_manifest: Path, commentary: str
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    payload = json.loads(_response("600000.SH"))
    payload["picks"][0]["reasoning"] = commentary

    with pytest.raises(ValueError, match="provider output reasoning"):
        create_selection(plan, json.dumps(payload, ensure_ascii=False))


def test_late_selection_is_never_oos(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert artifact.temporal_status == "retrospective_simulation"
    assert "selection_generated_after_as_of" in artifact.evidence_limitations


def test_retrospective_check_uses_cn_market_timezone(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 16, 30, tzinfo=timezone.utc),
    )
    assert artifact.temporal_status == "retrospective_simulation"


def test_retrospective_check_uses_us_market_timezone(us_manifest: Path) -> None:
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("AAPL", language="en"),
        generated_at=datetime(2026, 7, 16, 0, 30, tzinfo=timezone.utc),
    )
    assert artifact.temporal_status == "contemporaneous"
    assert artifact.point_in_time_assurance == "unverified"
    assert artifact.generated_at.tzinfo == timezone.utc
    assert artifact.picks[0].reasoning == (
        "The overall candidate score supports the relative rank for AAPL"
    )


def test_artifact_schema_recomputes_temporal_status(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump()
    payload["generated_at"] = datetime(2026, 7, 15, 16, 30, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="market timezone"):
        SelectionArtifact.model_validate(payload)


def test_artifact_schema_rejects_incomplete_hot_lineage(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump()
    payload["candidate_observation_date"] = None
    payload["candidate_generated_at"] = None
    payload["data_cutoff"] = None
    payload["upstream_execution_not_before"] = None

    with pytest.raises(ValueError, match="complete candidate timing"):
        SelectionArtifact.model_validate(payload)


def test_artifact_schema_enforces_hot_eod_cutoff(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump()
    payload["candidate_generated_at"] = datetime(2026, 7, 14, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="completed EOD cutoff"):
        SelectionArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response("600000.SH"), "exactly top_n"),
        (_response("600000.SH", "600000.SH"), "duplicate"),
        (_response("600000.SH", "000002.SZ"), "outside candidate"),
        (_response("600000.SH", "AAPL"), "invalid CN symbol"),
        ("not json", "strict schema"),
        ("```json\n{}", "malformed markdown"),
    ],
)
def test_selection_rejects_invalid_provider_output(
    cn_manifest: Path, response: str, message: str
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=2,
    )
    with pytest.raises(ValueError, match=message):
        create_selection(plan, response)


def test_strict_schema_rejects_extra_fields_and_float_confidence(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    extra = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "name": "model must not supply this",
                    "confidence_score": 8,
                    "reasoning": "reason",
                    "risk_note": "risk",
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="extra_forbidden"):
        create_selection(plan, extra)

    float_score = _response("600000.SH").replace(
        '"confidence_score": 9', '"confidence_score": 9.0'
    )
    with pytest.raises(ValueError, match="int_type"):
        create_selection(plan, float_score)


def test_well_formed_json_fence_is_tolerated(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        f"```json\n{_response('600000.SH')}\n```",
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    assert artifact.picks[0].symbol == "600000.SH"


def test_run_selection_accepts_injected_provider(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    observed: list[tuple[str, str, float]] = []

    def caller(prompt: str, model: str, timeout: float) -> str:
        observed.append((prompt, model, timeout))
        return _response("600000.SH")

    artifact = run_selection(
        plan,
        timeout=3.5,
        caller=caller,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    assert artifact.picks[0].symbol == "600000.SH"
    assert observed == [(plan.prompt, "deepseek-v4-flash", 3.5)]


def test_write_and_reload_selection(cn_manifest: Path, tmp_path: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    output = write_selection(artifact, tmp_path / "nested" / "picks.json")
    loaded = SelectionArtifact.model_validate_json(output.read_text(), strict=True)
    assert loaded == artifact
    assert not output.with_suffix(".json.tmp").exists()


def test_write_selection_never_overwrites_existing_artifact(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    output = tmp_path / "selection.json"
    output.write_text("existing receipt\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        write_selection(artifact, output)

    assert output.read_text(encoding="utf-8") == "existing receipt\n"
    assert list(tmp_path.glob(".selection.json.*.tmp")) == []


def test_selection_artifact_is_immutable(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="frozen"):
        artifact.temporal_status = "retrospective_simulation"


def test_concurrent_selection_writers_have_exactly_one_winner(
    cn_manifest: Path, tmp_path: Path
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    artifact = create_selection(
        plan,
        _response("600000.SH"),
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    output = tmp_path / "selection.json"

    def attempt_write() -> bool:
        try:
            write_selection(artifact, output)
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: attempt_write(), range(2)))

    assert sorted(results) == [False, True]
    assert SelectionArtifact.model_validate_json(output.read_text(), strict=True)
    assert list(tmp_path.glob(".selection.json.*.tmp")) == []


def test_artifact_rejects_naive_generation_time(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    with pytest.raises(ValueError, match="UTC offset"):
        create_selection(
            plan,
            _response("600000.SH"),
            generated_at=datetime(2026, 7, 15),
        )


def test_selection_rejects_causal_time_inversion(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    with pytest.raises(ValueError, match="manifest was generated after"):
        create_selection(
            plan,
            _response("600000.SH"),
            generated_at=datetime(2026, 7, 14, 21, 30, tzinfo=timezone.utc),
        )


def test_selection_cannot_precede_its_signal_date(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    with pytest.raises(ValueError, match="precedes the selection"):
        create_selection(
            plan,
            _response("600000.SH"),
            generated_at=datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc),
        )


def test_selection_rejects_oversized_provider_output(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    with pytest.raises(ValueError, match="1 MB"):
        create_selection(plan, "x" * 1_000_001)


def test_call_plan_provider_dispatches_by_market(
    cn_manifest: Path, us_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cn = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    us = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek",
        lambda prompt, **kwargs: (
            f"cn:{kwargs['model']}:{kwargs['timeout']}:{len(prompt)}"
        ),
    )
    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_gemini",
        lambda prompt, *, model, timeout: f"us:{model}:{timeout}:{len(prompt)}",
    )
    assert call_plan_provider(cn, timeout=2).startswith("cn:deepseek-v4-flash:2")
    assert call_plan_provider(us, timeout=4).startswith("us:gemini-2.5-flash:4")
