from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from stock_analysis.ai_lab.selection import build_selection_plan, create_selection


def _us_response(commentary: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": "AAPL",
                    "confidence_score": 9,
                    "reasoning": commentary,
                    "risk_note": (
                        "The overall candidate score leaves uncertainty for AAPL"
                    ),
                }
            ]
        }
    )


def _cn_response(reasoning: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 9,
                    "reasoning": reasoning,
                    "risk_note": "仅依据日内波动稳定性，风险解读仍有信息边界",
                }
            ]
        },
        ensure_ascii=False,
    )


def test_cn_selection_accepts_simplified_chinese_explanations(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    artifact = create_selection(plan, _cn_response("综合候选评分支持相对排序。"))

    assert artifact.picks[0].reasoning == "综合候选评分支持相对排序。"
    assert "日内波动稳定性" in artifact.picks[0].risk_note


def test_cn_commentary_allows_capital_participation_rate_description(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    reasoning = "依据综合候选评分，资金参与度不足。"

    artifact = create_selection(plan, _cn_response(reasoning))

    assert artifact.picks[0].reasoning == reasoning


def test_cn_commentary_still_rejects_participation_advice(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="trading advice or a return promise"):
        create_selection(plan, _cn_response("依据热点主题，可以参与该候选。"))


@pytest.mark.parametrize(
    ("feature", "value", "reasoning"),
    [
        ("source_topics", "大模型应用", "热点主题显示大模型应用活跃。"),
        ("source_topics", "大模型推理需求", "热点主题显示大模型推理需求活跃。"),
        ("source_concepts", "供应商生态", "关联概念显示供应商生态活跃。"),
    ],
)
def test_generic_model_and_supplier_text_requires_actual_candidate_value(
    cn_manifest: Path,
    feature: str,
    value: str,
    reasoning: str,
) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0][feature] = [value]
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    artifact = create_selection(plan, _cn_response(reasoning))

    assert artifact.picks[0].reasoning == reasoning


def test_cn_provider_like_concept_is_allowed_only_as_explicit_candidate_data(
    cn_manifest: Path,
) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0]["source_concepts"] = ["DeepSeek概念"]
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    reasoning = "关联概念：[DeepSeek概念]支持候选的相对排序。"

    artifact = create_selection(plan, _cn_response(reasoning))

    assert artifact.picks[0].reasoning == reasoning


def test_us_provider_like_concept_is_allowed_only_as_explicit_candidate_data(
    us_manifest: Path,
) -> None:
    manifest = json.loads(us_manifest.read_text(encoding="utf-8"))
    manifest["candidates"][0]["source_concepts"] = ["Gemini ecosystem"]
    us_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    reasoning = (
        "The related concepts: [Gemini ecosystem] support the relative comparison."
    )

    artifact = create_selection(plan, _us_response(reasoning))

    assert artifact.picks[0].reasoning == reasoning


@pytest.mark.parametrize(
    ("concept", "reasoning"),
    [
        ("DeepSeek概念", "关联概念中的DeepSeek概念支持相对排序。"),
        (
            "DeepSeek概念",
            "关联概念：[DeepSeek概念]支持排序，实际由DeepSeek解释。",
        ),
        ("API key", "关联概念：[API key]支持候选的相对排序。"),
        (
            "DeepSeek API key",
            "关联概念：[DeepSeek API key]支持候选的相对排序。",
        ),
    ],
)
def test_candidate_data_citation_does_not_disable_system_metadata_policy(
    cn_manifest: Path,
    concept: str,
    reasoning: str,
) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0]["source_concepts"] = [concept]
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="forbidden system metadata"):
        create_selection(plan, _cn_response(reasoning))


def test_provider_like_concept_cannot_be_relabelled_as_a_topic(
    cn_manifest: Path,
) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0]["source_concepts"] = ["DeepSeek概念"]
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="supplied candidate value"):
        create_selection(
            plan,
            _cn_response("热点主题：[DeepSeek概念]支持候选的相对排序。"),
        )


@pytest.mark.parametrize(
    "reasoning",
    ["热点主题显示大模型应用活跃。", "关联概念显示供应商生态活跃。"],
)
def test_topic_or_concept_text_cannot_invent_a_candidate_value(
    cn_manifest: Path,
    reasoning: str,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="supplied candidate value"):
        create_selection(plan, _cn_response(reasoning))


@pytest.mark.parametrize(
    "reasoning",
    [
        "热点主题中的银行和大模型应用共同支持排序。",
        "source_topics 中的银行与大模型推理需求共同支持排序。",
    ],
)
def test_categorical_grounding_cannot_mix_actual_and_invented_values(
    cn_manifest: Path,
    reasoning: str,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="unsupported source_topics value"):
        create_selection(plan, _cn_response(reasoning))


def test_categorical_grounding_rejects_invented_value_in_later_clause(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="unsupported categorical value"):
        create_selection(
            plan,
            _cn_response("热点主题中的银行支持排序，同时大模型应用也很活跃。"),
        )


@pytest.mark.parametrize(
    ("values", "reasoning"),
    [
        (["银行", "大模型应用"], "热点主题中的银行和大模型应用共同支持排序。"),
        (
            ["银行", "大模型推理需求"],
            "source_topics 中的银行与大模型推理需求共同支持排序。",
        ),
    ],
)
def test_categorical_grounding_allows_multiple_actual_values(
    cn_manifest: Path,
    values: list[str],
    reasoning: str,
) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0]["source_topics"] = values
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    artifact = create_selection(plan, _cn_response(reasoning))

    assert artifact.picks[0].reasoning == reasoning


def test_decimal_percentage_is_not_misclassified_as_a_host(cn_manifest: Path) -> None:
    manifest = json.loads(cn_manifest.read_text(encoding="utf-8"))
    manifest["candidate_universe"][0]["ret_5d"] = 0.0325
    cn_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    artifact = create_selection(plan, _cn_response("近5日表现为3.25%。"))

    assert artifact.picks[0].reasoning == "近5日表现为3.25%。"


def test_natural_alias_must_exist_on_the_selected_candidate(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="field absent from its candidate"):
        create_selection(
            plan,
            _cn_response("流动性特征支持该候选的相对排序。"),
        )


@pytest.mark.parametrize(
    "reasoning",
    [
        "综合候选评分支持排序，公司产品供不应求。",
        "综合候选评分支持排序，公司产销两旺。",
        "综合候选评分支持排序，公司订单饱满。",
    ],
)
def test_cn_commentary_rejects_external_operating_claim_synonyms(
    cn_manifest: Path,
    reasoning: str,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="external or future claim"):
        create_selection(plan, _cn_response(reasoning))


def test_unicode_skeleton_rejects_accented_provider_name(us_manifest: Path) -> None:
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="forbidden system metadata"):
        create_selection(
            plan,
            _us_response("The overall candidate score was interpreted by DëepSeek."),
        )


def test_unicode_skeleton_does_not_reject_ordinary_accented_word(
    us_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    commentary = "The overall candidate score supports a naïve relative comparison."

    artifact = create_selection(
        plan,
        _us_response(commentary),
        generated_at=datetime(2026, 7, 15, 16, tzinfo=timezone.utc),
    )

    assert artifact.picks[0].reasoning == commentary


@pytest.mark.parametrize(
    "commentary",
    [
        "The overall candidate score was interpreted by DеepSeek.",
        "The overall candidate score was interpreted by α model.",
        "The overall candidate score is detailed at 10.0.0.8.",
        "The overall candidate score is detailed at 2001:db8::8.",
        "The overall candidate score is detailed at 例子.测试.",
        "The overall candidate score is detailed at analyst@example.com.",
        "Intraday stability is high, which means high risk.",
        "Intraday stability is high, which means more volatile behavior.",
        "Intraday stability is low, which means low risk.",
        "Intraday stability is low, so risk is low.",
        "The overall candidate score does not support the rank; intuition does.",
        "The overall candidate score reflects customer demand and competition.",
        "Based on the overall candidate score, investors should go long.",
        "The overall candidate score was generated by a language model.",
        "The overall candidate score was generated by a model.",
        "The overall candidate score was generated by an LLM.",
        "The overall candidate score includes provider name metadata.",
        "The overall candidate score is detailed at example.tech/path.",
        "综合候选评分 supports the relative ranking.",
        (
            "The ranking is not based on the overall candidate score; personal "
            "judgment is."
        ),
        "The overall candidate score suggests increasing exposure.",
        "Intraday stability is high, but the behavior is unstable.",
        "Intraday stability is low, yet it is more stable.",
    ],
)
def test_us_commentary_rejects_reviewer_policy_regressions(
    us_manifest: Path,
    commentary: str,
) -> None:
    plan = build_selection_plan(
        market="US",
        candidates_path=us_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    with pytest.raises(ValueError, match="provider output reasoning"):
        create_selection(plan, _us_response(commentary))
