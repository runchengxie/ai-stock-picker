from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import write_manifest

from stock_analysis.ai_lab.contracts import PromptProfile
from stock_analysis.ai_lab.frozen_plan import load_pick_plan, write_pick_plan
from stock_analysis.ai_lab.providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    OPENAI_SYSTEM_MESSAGE,
    ProviderExchange,
    deepseek_request_parameters,
)
from stock_analysis.ai_lab.ranking_policy import (
    policy_partitions,
    risk_veto_partitions,
)
from stock_analysis.ai_lab.ranking_policy_contract import (
    BOUNDED_RANKING_V3_POLICY,
    RISK_VETO_POLICY,
)
from stock_analysis.ai_lab.selection import build_selection_plan
from stock_analysis.ai_lab.shadow_campaign import (
    ShadowModel,
    ShadowProvider,
    run_shadow_day,
)
from stock_analysis.ai_lab.shadow_contract import (
    shadow_response_schema,
    shadow_response_schema_name,
)
from stock_analysis.ai_lab.shadow_validation import (
    validate_shadow_campaign,
    validate_shadow_day,
)

_AFTER_CLOSE = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


def _frozen_plan(tmp_path: Path, profile: PromptProfile) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "ts_code": f"{600000 + index:06d}.SH",
            "name": f"候选{index:02d}",
            "score": 100.0 - index,
            "relevance": 1.0 - index / 100,
            "source_topics": [f"主题{index % 3}"],
            "source_concepts": [f"概念{index % 4}"],
            "trend_score": round(1.0 - index / 50, 4),
            "risk_score": round(0.9 - index / 100, 4),
            "ret_5d": round(index / 100, 4),
            "amount_ratio": round(1.0 + index / 10, 4),
        }
        for index in range(1, 21)
    ]
    candidates = write_manifest(tmp_path / "candidates.json", rows=rows)
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=date(2026, 7, 15),
        top_n=10,
        style="momentum",
        prompt_profile=profile,
    )
    root = write_pick_plan(plan, tmp_path / "frozen-plan")
    return load_pick_plan(root / "plan.json")


def _exchange(plan: Any, model: ShadowModel, response: str) -> ProviderExchange:
    if model.provider == "openai":
        request = {
            "model": model.model,
            "instructions": OPENAI_SYSTEM_MESSAGE,
            "input": plan.prompt,
            "store": False,
            "max_output_tokens": model.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": shadow_response_schema_name(plan),
                    "strict": True,
                    "schema": shadow_response_schema(plan),
                }
            },
        }
        raw_response = {
            "model": f"{model.model}-actual",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": response}],
                }
            ],
        }
        endpoint = "https://api.openai.com/v1/responses"
    else:
        request = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
                {"role": "user", "content": plan.prompt},
            ],
            **deepseek_request_parameters(
                parameter_schema="explicit_v2",
                thinking=model.thinking,
                reasoning_effort=model.reasoning_effort,
                max_tokens=model.max_output_tokens,
            ),
        }
        raw_response = {
            "model": f"{model.model}-actual",
            "choices": [{"message": {"content": response}}],
        }
        endpoint = "https://api.deepseek.com/v1/chat/completions"
    response_body = json.dumps(raw_response, ensure_ascii=False).encode()
    return ProviderExchange(
        provider=model.provider,
        model=model.model,
        endpoint=endpoint,
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=json.dumps(request, ensure_ascii=False).encode(),
        response_body=response_body,
        response_text=response,
        actual_model=f"{model.model}-actual",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def _ranking_response(symbols: tuple[str, ...], *, extra: bool = False) -> str:
    picks = [{"symbol": symbol, "confidence_score": 8} for symbol in symbols]
    if extra:
        picks[0]["reasoning"] = "不应被严格排名合同接受"
    return json.dumps({"picks": picks}, ensure_ascii=False)


def test_prompt_8_is_unambiguous_and_keeps_legacy_7_available(tmp_path: Path) -> None:
    current = _frozen_plan(tmp_path / "current", "bounded_ranking_v3")
    legacy = _frozen_plan(tmp_path / "legacy", "bounded_ranking_v2")

    prompt = json.loads(current.prompt)
    constraints = " ".join(prompt["constraints"])
    assert current.prompt_version == "2026-07-18.8"
    assert "reasoning, risk_note" in constraints
    assert "Write reasoning and risk_note" not in constraints
    assert current.ranking_policy == BOUNDED_RANKING_V3_POLICY
    assert legacy.prompt_version == "2026-07-17.7"


def test_bounded_v3_requires_three_actual_two_of_three_winners(tmp_path: Path) -> None:
    plan = _frozen_plan(tmp_path, "bounded_ranking_v3")
    model = ShadowModel(provider="openai", model="gpt-test")
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V3_POLICY)
    rankings = (
        (*locked, boundary[0], boundary[1], boundary[2]),
        (*locked, boundary[3], boundary[4], boundary[5]),
        (*locked, boundary[5], boundary[6], boundary[7]),
    )

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="bounded-majority",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, repetition, _timeout: _exchange(
            owner_plan,
            owner_model,
            _ranking_response(rankings[repetition - 1]),
        ),
    )
    summary = validate_shadow_day(result.day_root)

    assert "/bounded_ranking/" in str(result.day_root)
    assert result.consensus_status == "tombstone"
    assert summary["valid_repetitions"] == [1, 2, 3]
    assert summary["selected_symbols"] is None
    assert summary["effective_symbols"] == summary["numeric_fallback_symbols"]
    manifest = json.loads(
        (result.day_root / "consensus" / "manifest.json").read_bytes()
    )
    assert manifest["tombstone_reason"] == "insufficient_consensus_agreement"


@pytest.mark.parametrize("profile", ["bounded_ranking_v3", "risk_veto_v1"])
def test_prompt_8_prospective_run_fails_closed_without_launch_receipt(
    tmp_path: Path, profile: PromptProfile
) -> None:
    plan = _frozen_plan(tmp_path, profile)
    model = ShadowModel(provider="openai", model="gpt-test")

    with pytest.raises(ValueError, match="provider-neutral decision plan"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="unbound-prospective",
            signal_date=date(2026, 7, 15),
            shadow_model=model,
            generated_at=_AFTER_CLOSE,
        )

    assert not (tmp_path / "shadow").exists()


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_prompt_8_uses_same_strict_local_parser_for_both_providers(
    tmp_path: Path, provider: ShadowProvider
) -> None:
    plan = _frozen_plan(tmp_path, "bounded_ranking_v3")
    model = ShadowModel(provider=provider, model=f"{provider}-test")
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V3_POLICY)
    ranking = (*locked, *boundary[:3])

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id=f"strict-{provider}",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, _repetition, _timeout: _exchange(
            owner_plan,
            owner_model,
            _ranking_response(ranking, extra=True),
        ),
    )

    assert result.repetition_statuses == ("tombstone", "tombstone", "tombstone")
    assert result.consensus_status == "tombstone"


def test_risk_veto_rep3_consensus_applies_only_numeric_replacement(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path, "risk_veto_v1")
    model = ShadowModel(provider="openai", model="gpt-test")
    selected, reserves = risk_veto_partitions(plan.universe, RISK_VETO_POLICY)
    responses = (
        {"veto_symbol": selected[0], "risk_code": "overheat"},
        {"veto_symbol": selected[0], "risk_code": "overheat"},
        {"veto_symbol": "NONE", "risk_code": "none"},
    )

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="risk-veto",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, repetition, _timeout: _exchange(
            owner_plan,
            owner_model,
            json.dumps(responses[repetition - 1]),
        ),
    )
    summary = validate_shadow_day(result.day_root)

    assert "/risk_veto/" in str(result.day_root)
    assert result.consensus_status == "complete"
    assert summary["arm"] == "risk_veto"
    assert summary["prompt_profile"] == "risk_veto_v1"
    assert isinstance(summary["numeric_ranking_sha256"], str)
    assert len(summary["numeric_ranking_sha256"]) == 64
    assert isinstance(summary["consensus_manifest_sha256"], str)
    assert len(summary["consensus_manifest_sha256"]) == 64
    assert summary["selected_symbols"] == [*selected[1:], reserves[0]]
    assert summary["numeric_fallback_symbols"] == list(selected)
    assert validate_shadow_campaign(result.day_root.parents[2])["day_count"] == 1


def test_risk_veto_requires_exact_decision_majority(tmp_path: Path) -> None:
    plan = _frozen_plan(tmp_path, "risk_veto_v1")
    model = ShadowModel(provider="deepseek", model="deepseek-test")
    selected, _reserves = risk_veto_partitions(plan.universe, RISK_VETO_POLICY)
    responses = (
        {"veto_symbol": selected[0], "risk_code": "overheat"},
        {"veto_symbol": selected[0], "risk_code": "instability"},
        {"veto_symbol": "NONE", "risk_code": "none"},
    )

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="risk-no-majority",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda owner_plan, owner_model, repetition, _timeout: _exchange(
            owner_plan,
            owner_model,
            json.dumps(responses[repetition - 1]),
        ),
    )
    summary = validate_shadow_day(result.day_root)

    assert result.consensus_status == "tombstone"
    assert summary["selected_symbols"] is None
    assert summary["effective_symbols"] == list(selected)
