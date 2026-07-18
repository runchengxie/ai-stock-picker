from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from stock_analysis.ai_lab.contracts import canonical_contract_sha256
from stock_analysis.ai_lab.evidence import validate_selection_evidence
from stock_analysis.ai_lab.evidence_consistency import provider_parameters
from stock_analysis.ai_lab.frozen_plan import write_pick_plan
from stock_analysis.ai_lab.providers import DEEPSEEK_SYSTEM_MESSAGE, ProviderExchange
from stock_analysis.ai_lab.ranking_policy_contract import (
    BOUNDED_RANKING_POLICY,
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V3_POLICY,
    RISK_VETO_POLICY,
)
from stock_analysis.ai_lab.selection import build_selection_plan
from stock_analysis.app.cli import create_parser, main


def _exchange(plan: Any, response: str) -> ProviderExchange:
    request = {
        "model": plan.model,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
            {"role": "user", "content": plan.prompt},
        ],
        **provider_parameters(plan),
    }
    response_body = json.dumps(
        {
            "model": f"{plan.model}-actual",
            "choices": [{"message": {"content": response}}],
        },
        ensure_ascii=False,
    ).encode()
    return ProviderExchange(
        provider=plan.provider,
        model=plan.model,
        endpoint="https://api.deepseek.com/v1/chat/completions",
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=json.dumps(request, ensure_ascii=False).encode(),
        response_body=response_body,
        response_text=response,
        actual_model=f"{plan.model}-actual",
        extraction_error=None,
        timeout_seconds=17.0,
    )


def test_contract_info_is_network_free_and_machine_readable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("contract-info must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )

    assert main(["cn", "contract-info"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_type"] == "ai_stock_picker_contract_info"
    assert payload["market"] == "CN"
    assert payload["provider"] == "deepseek"
    assert payload["schema_version"] == "1.2.0"
    assert payload["selection_contract"] == {
        "artifact_type": "ai_stock_selection",
        "schema_version": "1.0.0",
    }
    assert payload["prompt_profiles"] == {
        "bounded_ranking_v1": {
            "output_contract": "research_selection_or_ranking_diagnostic",
            "prompt_version": "2026-07-17.2",
            "ranking_policy": BOUNDED_RANKING_POLICY.contract_record(),
        },
        "bounded_ranking_v2": {
            "output_contract": "research_selection_or_ranking_diagnostic",
            "prompt_version": "2026-07-17.7",
            "ranking_policy": BOUNDED_RANKING_V2_POLICY.contract_record(),
        },
        "bounded_ranking_v3": {
            "output_contract": "strict_ranking_selection",
            "prompt_version": "2026-07-18.8",
            "ranking_policy": BOUNDED_RANKING_V3_POLICY.contract_record(),
        },
        "legacy_stability_v3": {
            "output_contract": "legacy_stability_selection",
            "prompt_version": "2026-07-15.3",
        },
        "production_v4": {
            "output_contract": "publication_selection",
            "prompt_version": "2026-07-17.6",
        },
        "ranking_only_v1": {
            "output_contract": "research_selection_or_ranking_diagnostic",
            "prompt_version": "2026-07-17.1",
        },
        "risk_veto_v1": {
            "output_contract": "strict_risk_veto_decision",
            "prompt_version": "2026-07-18.8",
            "risk_veto_policy": RISK_VETO_POLICY.contract_record(),
        },
    }
    assert payload["shadow_campaign_contract"]["repetitions"] == 3
    assert payload["shadow_campaign_contract"]["min_valid_repetitions"] == 2
    assert (
        payload["shadow_campaign_contract"]["model_partition_source"]
        == "ai_shadow_launch_receipt"
    )
    assert payload["shadow_campaign_contract"]["evidence_statuses"] == [
        "prospective_bound",
        "legacy_unbound",
    ]
    assert payload["accepted_candidate_contracts"]["hot_sector_candidate_universe_v2"][
        "source_concepts_policy_sha256"
    ].startswith("d14282e8")
    assert payload["model_response_contracts"]["ranking_selection"]["sha256"]
    assert payload["contract_sha256"] == canonical_contract_sha256(payload)


def test_contract_info_exposes_its_json_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["cn", "contract-info", "--json-schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "ContractInfoArtifact"
    assert schema["properties"]["contract_sha256"]["type"] == "string"


def test_us_contract_and_cli_do_not_advertise_cn_bounded_profile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["us", "contract-info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "bounded_ranking_v1" not in payload["prompt_profiles"]
    assert "bounded_ranking_v2" not in payload["prompt_profiles"]
    assert "bounded_ranking_v3" not in payload["prompt_profiles"]
    assert "risk_veto_v1" not in payload["prompt_profiles"]

    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "us",
                "pick-plan",
                "--candidates",
                "unused.json",
                "--as-of",
                "2026-07-15",
                "--top-n",
                "10",
                "--prompt-profile",
                "bounded_ranking_v1",
                "--output-dir",
                "unused",
            ]
        )


def test_ranking_only_trial_writes_current_selection_not_legacy_stability(
    cn_manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        prompt_profile="ranking_only_v1",
    )
    root = write_pick_plan(plan, tmp_path / "ranking-plan")
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选的相对排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda frozen, **_kwargs: _exchange(frozen, response),
    )
    output = tmp_path / "ranking-selection.json"

    assert main(_trial_args(root, output)) == 0

    selection = json.loads(output.read_bytes())
    assert selection["prompt_version"] == "2026-07-17.1"
    manifest = validate_selection_evidence(Path(f"{output}.evidence"))
    assert manifest["prompt_profile"] == "ranking_only_v1"
    assert manifest["ranking_contract"] == "passed"
    assert manifest["publication_contract"] == "passed"
    assert manifest["research_only"] is True


def test_ranking_only_minimal_response_persists_research_selection(
    cn_manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        prompt_profile="ranking_only_v1",
    )
    root = write_pick_plan(plan, tmp_path / "minimal-ranking-plan")
    response = json.dumps(
        {"picks": [{"symbol": "600000.SH", "confidence_score": 8}]},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda frozen, **_kwargs: _exchange(frozen, response),
    )
    output = tmp_path / "no-publication-selection.json"

    assert main(_trial_args(root, output)) == 0

    selection = json.loads(output.read_bytes())
    assert selection["picks"][0]["reasoning"] == ""
    assert selection["picks"][0]["risk_note"] == ""
    evidence = Path(f"{output}.evidence")
    manifest = validate_selection_evidence(evidence)
    assert manifest["status"] == "complete"
    assert manifest["ranking_contract"] == "passed"
    assert manifest["publication_contract"] == "passed"
    assert manifest["selection_path"] == "selection.json"
    assert manifest["research_only"] is True


def _trial_args(root: Path, output: Path) -> list[str]:
    return [
        "cn",
        "trial",
        "--plan",
        str(root / "plan.json"),
        "--output",
        str(output),
    ]
