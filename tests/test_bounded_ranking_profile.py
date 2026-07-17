from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from conftest import write_manifest

from stock_analysis.ai_lab.evidence import (
    validate_selection_evidence,
    write_selection_evidence,
)
from stock_analysis.ai_lab.evidence_consistency import provider_parameters
from stock_analysis.ai_lab.frozen_plan import load_pick_plan
from stock_analysis.ai_lab.providers import DEEPSEEK_SYSTEM_MESSAGE, ProviderExchange
from stock_analysis.ai_lab.ranking_policy import (
    numeric_ranked_candidates,
    policy_partitions,
)
from stock_analysis.ai_lab.ranking_policy_contract import (
    BOUNDED_RANKING_POLICY,
    BOUNDED_RANKING_PROMPT_VERSION,
    BOUNDED_RANKING_V2_POLICY,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
)
from stock_analysis.ai_lab.selection import build_selection_plan, create_selection
from stock_analysis.app.cli import main


def _bounded_manifest(tmp_path: Path, *, count: int = 20) -> Path:
    rows = [
        {
            "ts_code": f"{600000 + index:06d}.SH",
            "name": f"候选{index:02d}",
            "score": 100.0 - index,
            "relevance": 1.0 - index / 100,
            "source_topics": [f"主题{index % 4}"],
            "source_concepts": [f"概念{index % 3}"],
            "trend_score": round(1.0 - index / 50, 4),
            "risk_score": round(0.9 - index / 100, 4),
        }
        for index in range(1, count + 1)
    ]
    return write_manifest(tmp_path / "bounded.json", rows=rows)


def _bounded_plan(path: Path) -> Any:
    return build_selection_plan(
        market="CN",
        candidates_path=path,
        as_of=date(2026, 7, 15),
        top_n=10,
        style="momentum",
        prompt_profile="bounded_ranking_v1",
    )


def _bounded_v2_plan(path: Path) -> Any:
    return build_selection_plan(
        market="CN",
        candidates_path=path,
        as_of=date(2026, 7, 15),
        top_n=10,
        style="momentum",
        prompt_profile="bounded_ranking_v2",
    )


def _response(symbols: tuple[str, ...]) -> str:
    return json.dumps(
        {"picks": [{"symbol": symbol, "confidence_score": 8} for symbol in symbols]},
        ensure_ascii=False,
    )


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


def test_bounded_prompt_hides_scores_and_blinds_boundary_order(tmp_path: Path) -> None:
    plan = _bounded_plan(_bounded_manifest(tmp_path))
    ranked = numeric_ranked_candidates(plan.universe)
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_POLICY)
    prompt = json.loads(plan.prompt)

    assert plan.prompt_version == BOUNDED_RANKING_PROMPT_VERSION
    assert plan.research_only is True
    assert plan.presentation_order != tuple(item.symbol for item in ranked)
    assert prompt["locked_prefix"] == list(locked)
    rows = prompt["boundary_candidates"]
    assert [row["symbol"] for row in rows] == [
        symbol for symbol in plan.presentation_order if symbol in set(boundary)
    ]
    assert [row["symbol"] for row in rows] != list(boundary)
    assert {row["numeric_score_level"] for row in rows} == {
        "upper",
        "middle",
        "lower",
    }
    assert all("score" not in row for row in rows)
    assert all(
        "score" not in row["features"] and "relevance" not in row["features"]
        for row in rows
    )
    assert '"score":' not in plan.prompt
    assert '"relevance":' not in plan.prompt
    assert sha256(plan.prompt.encode()).hexdigest() == (
        "9704eba8a38f3585beeb6dbefb9c8cf6851621573d75fab5fdef47ad1b44adb2"
    )


def test_bounded_v2_uses_one_uniform_anonymous_boundary_band(tmp_path: Path) -> None:
    plan = _bounded_v2_plan(_bounded_manifest(tmp_path))
    ranked = numeric_ranked_candidates(plan.universe)
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V2_POLICY)
    prompt = json.loads(plan.prompt)

    assert plan.prompt_version == BOUNDED_RANKING_V2_PROMPT_VERSION
    assert plan.presentation_order != tuple(item.symbol for item in ranked)
    assert prompt["locked_prefix"] == list(locked)
    rows = prompt["boundary_candidates"]
    assert [row["symbol"] for row in rows] == [
        symbol for symbol in plan.presentation_order if symbol in set(boundary)
    ]
    assert {row["boundary_band"] for row in rows} == {"eligible"}
    assert all("numeric_score_level" not in row for row in rows)
    assert all("numeric_rank" not in row for row in rows)
    assert all("score" not in row for row in rows)
    assert all(
        "numeric_rank" not in row["features"]
        and "score" not in row["features"]
        and "relevance" not in row["features"]
        for row in rows
    )
    assert not any(label in plan.prompt for label in ('"upper"', '"middle"', '"lower"'))
    assert plan.ranking_policy_record == {
        **BOUNDED_RANKING_V2_POLICY.contract_record(),
        "numeric_ranking_method": "relevance_desc_score_desc_symbol_asc",
        "locked_prefix_symbols": list(locked),
        "boundary_symbols": list(boundary),
    }


def test_bounded_v2_pick_plan_round_trips_without_a_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _bounded_manifest(tmp_path)

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded v2 pick-plan must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    root = tmp_path / "v2-plan"
    assert (
        main(
            [
                "cn",
                "pick-plan",
                "--candidates",
                str(path),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "10",
                "--prompt-profile",
                "bounded_ranking_v2",
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )

    rebuilt = load_pick_plan(root / "plan.json")
    payload = json.loads((root / "plan.json").read_bytes())
    assert rebuilt.prompt_profile == "bounded_ranking_v2"
    assert rebuilt.prompt_version == BOUNDED_RANKING_V2_PROMPT_VERSION
    assert payload["ranking_policy"] == rebuilt.ranking_policy_record
    assert '"numeric_score_level"' not in rebuilt.prompt


def test_bounded_validator_accepts_boundary_reorder_and_records_policy(
    tmp_path: Path,
) -> None:
    plan = _bounded_plan(_bounded_manifest(tmp_path))
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_POLICY)
    symbols = (*locked, boundary[2], boundary[7], boundary[0])
    response = _response(symbols)
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )

    assert tuple(pick.symbol for pick in artifact.picks) == symbols
    assert BOUNDED_RANKING_POLICY.selection_limitation in artifact.evidence_limitations
    evidence = write_selection_evidence(
        plan,
        _exchange(plan, response),
        artifact,
        tmp_path / "bounded-evidence",
    )
    manifest = validate_selection_evidence(evidence)
    assert manifest["prompt_profile"] == "bounded_ranking_v1"
    assert manifest["prompt_version"] == BOUNDED_RANKING_PROMPT_VERSION
    assert manifest["ranking_policy"] == plan.ranking_policy_record
    assert manifest["research_only"] is True


def test_bounded_validator_rejects_locked_prefix_change_and_outside_boundary(
    tmp_path: Path,
) -> None:
    plan = _bounded_plan(_bounded_manifest(tmp_path))
    ranked = numeric_ranked_candidates(plan.universe)
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_POLICY)
    changed_prefix = (locked[1], locked[0], *locked[2:], *boundary[:3])
    with pytest.raises(ValueError, match="locked Numeric prefix"):
        create_selection(plan, _response(changed_prefix))

    outside_boundary = (*locked, boundary[0], boundary[1], ranked[15].symbol)
    with pytest.raises(ValueError, match="outside ranks 8-15"):
        create_selection(plan, _response(outside_boundary))


def test_bounded_plan_rejects_canonical_presentation_and_wrong_shape(
    tmp_path: Path,
) -> None:
    path = _bounded_manifest(tmp_path)
    baseline = _bounded_plan(path)
    canonical = [item.symbol for item in numeric_ranked_candidates(baseline.universe)]
    with pytest.raises(ValueError, match="deterministic blinded"):
        build_selection_plan(
            market="CN",
            candidates_path=path,
            as_of=date(2026, 7, 15),
            top_n=10,
            prompt_profile="bounded_ranking_v1",
            presentation_order=canonical,
        )
    with pytest.raises(ValueError, match="requires top_n=10"):
        build_selection_plan(
            market="CN",
            candidates_path=path,
            as_of=date(2026, 7, 15),
            top_n=9,
            prompt_profile="bounded_ranking_v1",
        )


def test_bounded_cli_plan_and_dry_run_are_network_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _bounded_manifest(tmp_path)

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded plan and dry-run must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    root = tmp_path / "plan"
    assert (
        main(
            [
                "cn",
                "pick-plan",
                "--candidates",
                str(path),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "10",
                "--prompt-profile",
                "bounded_ranking_v1",
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )
    plan_payload = json.loads((root / "plan.json").read_bytes())
    assert plan_payload["ranking_policy"]["policy_id"] == (
        BOUNDED_RANKING_POLICY.policy_id
    )
    capsys.readouterr()

    assert (
        main(
            [
                "cn",
                "pick",
                "--candidates",
                str(path),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "10",
                "--prompt-profile",
                "bounded_ranking_v1",
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["prompt_profile"] == "bounded_ranking_v1"
    assert dry_run["prompt_version"] == BOUNDED_RANKING_PROMPT_VERSION
    assert dry_run["ranking_policy"]["policy_id"] == BOUNDED_RANKING_POLICY.policy_id


def test_production_prompt_golden_is_unchanged(cn_manifest: Path) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    assert sha256(plan.prompt.encode()).hexdigest() == (
        "2a5de20d63e72dc8c4c0a62ef347c4942eafc7d783e230ce80a49b29f3a42037"
    )
    assert plan.ranking_policy is None
    assert plan.ranking_policy_fields == {}
