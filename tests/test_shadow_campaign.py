from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import write_manifest

from stock_analysis.ai_lab.contracts import RankingModelSelection, Style
from stock_analysis.ai_lab.frozen_plan import load_pick_plan, write_pick_plan
from stock_analysis.ai_lab.providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    OPENAI_SYSTEM_MESSAGE,
    ProviderError,
    ProviderExchange,
    deepseek_request_parameters,
)
from stock_analysis.ai_lab.ranking_policy import policy_partitions
from stock_analysis.ai_lab.ranking_policy_contract import BOUNDED_RANKING_V2_POLICY
from stock_analysis.ai_lab.selection import build_selection_plan
from stock_analysis.ai_lab.shadow_campaign import (
    ShadowModel,
    finalize_shadow_day,
    run_shadow_day,
    shadow_day_path,
)
from stock_analysis.ai_lab.shadow_validation import (
    validate_shadow_campaign,
    validate_shadow_day,
    validate_shadow_repetition,
)
from stock_analysis.app.cli import main

_AFTER_CLOSE = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


def _frozen_plan(
    tmp_path: Path,
    *,
    signal_date: date = date(2026, 7, 15),
    candidate_generated_at: str | None = None,
    style: Style = "momentum",
) -> Any:
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
        }
        for index in range(1, 21)
    ]
    overrides = (
        {"generated_at": candidate_generated_at}
        if candidate_generated_at is not None
        else {}
    )
    candidates = write_manifest(tmp_path / "bounded.json", rows=rows, **overrides)
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=signal_date,
        top_n=10,
        style=style,
        prompt_profile="bounded_ranking_v2",
    )
    root = write_pick_plan(plan, tmp_path / "frozen-plan")
    return load_pick_plan(root / "plan.json")


def _response(symbols: tuple[str, ...], *, publication_fail: bool = False) -> str:
    picks: list[dict[str, object]] = [
        {"symbol": symbol, "confidence_score": 8} for symbol in symbols
    ]
    if publication_fail:
        picks[0]["reasoning"] = "立即买入并保证上涨。"
    return json.dumps({"picks": picks}, ensure_ascii=False)


def _exchange(plan: Any, model: ShadowModel, response: str) -> ProviderExchange:
    usage = {"input_tokens": 10, "output_tokens": 5}
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
                    "name": "ai_stock_ranking",
                    "strict": True,
                    "schema": RankingModelSelection.model_json_schema(),
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
            "usage": usage,
        }
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
            "usage": usage,
        }
    response_body = json.dumps(raw_response, ensure_ascii=False).encode()
    return ProviderExchange(
        provider=model.provider,
        model=model.model,
        endpoint=(
            "https://api.openai.com/v1/responses"
            if model.provider == "openai"
            else "https://api.deepseek.com/v1/chat/completions"
        ),
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
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _rankings(plan: Any) -> tuple[tuple[str, ...], ...]:
    locked, boundary = policy_partitions(plan.universe, BOUNDED_RANKING_V2_POLICY)
    return (
        (*locked, boundary[0], boundary[1], boundary[2]),
        (*locked, boundary[1], boundary[0], boundary[3]),
        (*locked, boundary[1], boundary[2], boundary[0]),
    )


def test_shadow_day_runs_three_repetitions_and_builds_deterministic_consensus(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)

    def caller(
        _plan: Any, supplied_model: ShadowModel, repetition: int, _timeout: float
    ) -> ProviderExchange:
        return _exchange(
            _plan,
            supplied_model,
            _response(rankings[repetition - 1], publication_fail=repetition == 1),
        )

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="bounded-v2",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=caller,
    )
    summary = validate_shadow_day(result.day_root)

    assert result.repetition_statuses == ("complete", "complete", "complete")
    assert result.consensus_status == "complete"
    assert summary["valid_repetitions"] == [1, 2, 3]
    assert summary["selected_symbols"] == [
        *rankings[0][:7],
        rankings[0][8],
        rankings[0][7],
        rankings[0][9],
    ]
    assert summary["selection_source"] == "bounded_ranking_consensus"
    first_manifest = json.loads(
        (result.day_root / "repetition-01" / "manifest.json").read_bytes()
    )
    assert first_manifest["ranking_contract"] == "passed"
    assert first_manifest["publication_contract"] == "failed"
    assert first_manifest["status"] == "complete"
    assert first_manifest["actual_model"] == "gpt-test-actual"
    assert first_manifest["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert (result.day_root / "repetition-01" / "ranking.json").is_file()
    assert (result.day_root / "repetition-01" / "numeric_ranking.json").is_file()
    with pytest.raises(FileExistsError, match="already exists"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="bounded-v2",
            signal_date=date(2026, 7, 15),
            shadow_model=model,
            generated_at=_AFTER_CLOSE,
            caller=caller,
        )


def test_one_failed_repetition_still_reaches_min_two_consensus(tmp_path: Path) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="deepseek", model="deepseek-test")
    rankings = _rankings(plan)

    def caller(
        _plan: Any, supplied_model: ShadowModel, repetition: int, _timeout: float
    ) -> ProviderExchange:
        if repetition == 2:
            raise ProviderError("sanitized failure")
        return _exchange(_plan, supplied_model, _response(rankings[repetition - 1]))

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="two-valid",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=caller,
    )
    summary = validate_shadow_day(result.day_root)
    assert result.repetition_statuses == ("complete", "tombstone", "complete")
    assert result.consensus_status == "complete"
    assert summary["valid_repetitions"] == [1, 3]


def test_less_than_two_valid_writes_consensus_tombstone_and_numeric_fallback(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)

    def caller(
        _plan: Any, supplied_model: ShadowModel, repetition: int, _timeout: float
    ) -> ProviderExchange:
        if repetition != 1:
            raise ProviderError("sanitized failure")
        return _exchange(_plan, supplied_model, _response(rankings[0]))

    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="one-valid",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=caller,
    )
    summary = validate_shadow_day(result.day_root)

    assert result.consensus_status == "tombstone"
    assert summary["selected_symbols"] is None
    assert summary["selection_source"] == "numeric_fallback"
    assert summary["effective_symbols"] == summary["numeric_fallback_symbols"]
    assert len(cast(list[str], summary["numeric_fallback_symbols"])) == 10


def test_watchdog_terminalizes_units_left_missing_by_interruption(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)

    def interrupted(
        _plan: Any, supplied_model: ShadowModel, repetition: int, _timeout: float
    ) -> ProviderExchange:
        if repetition == 2:
            raise KeyboardInterrupt
        return _exchange(_plan, supplied_model, _response(rankings[0]))

    with pytest.raises(KeyboardInterrupt):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="interrupted",
            signal_date=date(2026, 7, 15),
            shadow_model=model,
            generated_at=_AFTER_CLOSE,
            caller=interrupted,
        )

    result = finalize_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="interrupted",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
    )
    summary = validate_shadow_day(result.day_root)
    assert result.repetition_statuses == ("complete", "tombstone", "tombstone")
    assert summary["consensus_status"] == "tombstone"
    watchdog_manifest = json.loads(
        (result.day_root / "repetition-02" / "manifest.json").read_bytes()
    )
    assert watchdog_manifest["tombstone_reason"] == "watchdog_missing_repetition"


def test_shadow_validators_and_cli_fail_closed_on_tampering(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)
    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="validated",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings[repetition - 1])
        ),
    )

    assert main(["cn", "validate-shadow-day", "--day-dir", str(result.day_root)]) == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["valid"] is True
    campaign_summary = validate_shadow_campaign(result.day_root.parents[1])
    assert campaign_summary["day_count"] == 1

    ranking_path = result.day_root / "repetition-01" / "ranking.json"
    ranking_path.write_bytes(ranking_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_shadow_day(result.day_root)


def test_shadow_day_and_watchdog_cli_use_the_owner_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _frozen_plan(tmp_path)
    rankings = _rankings(plan)

    def provider(
        _plan: Any, supplied_model: ShadowModel, repetition: int, _timeout: float
    ) -> ProviderExchange:
        return _exchange(_plan, supplied_model, _response(rankings[repetition - 1]))

    monkeypatch.setattr(
        "stock_analysis.ai_lab.shadow_campaign.call_shadow_provider", provider
    )
    args = [
        "--plan",
        str(tmp_path / "frozen-plan" / "plan.json"),
        "--campaign-id",
        "cli-shadow",
        "--signal-date",
        "2026-07-15",
        "--output-root",
        str(tmp_path / "shadow"),
        "--provider",
        "openai",
        "--model",
        "gpt-test",
    ]
    assert main(["cn", "shadow-day", *args]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["repetition_statuses"] == ["complete", "complete", "complete"]
    assert result["consensus_status"] == "complete"

    assert main(["cn", "shadow-watchdog", *args]) == 0
    watchdog = json.loads(capsys.readouterr().out)
    assert watchdog == result


def test_shadow_rejects_preclose_execution_and_openai_deepseek_parameters(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)

    def unexpected(*_args: object) -> ProviderExchange:
        raise AssertionError("provider must not be called")

    with pytest.raises(ValueError, match="after the signal-date close"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="preclose",
            signal_date=date(2026, 7, 15),
            shadow_model=ShadowModel(provider="openai", model="gpt-test"),
            generated_at=datetime(2026, 7, 15, 7, tzinfo=timezone.utc),
            caller=unexpected,
        )
    with pytest.raises(ValueError, match="does not accept DeepSeek"):
        ShadowModel(
            provider="openai",
            model="gpt-test",
            thinking="enabled",
            reasoning_effort="high",
        )


def test_shadow_rejects_candidate_created_after_the_claimed_execution(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(
        tmp_path,
        candidate_generated_at="2026-07-15T17:00:00+08:00",
    )

    def unexpected(*_args: object) -> ProviderExchange:
        raise AssertionError("provider must not be called")

    with pytest.raises(ValueError, match="generated after shadow execution"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="future-input",
            signal_date=date(2026, 7, 15),
            shadow_model=ShadowModel(provider="openai", model="gpt-test"),
            generated_at=_AFTER_CLOSE,
            caller=unexpected,
        )


def test_atomic_staging_leaves_no_partial_partition_and_watchdog_can_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock_analysis.ai_lab import shadow_campaign

    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)
    original = shadow_campaign._write_exclusive

    def interrupted_write(path: Path, payload: bytes) -> None:
        if path.name == "numeric_ranking.json":
            raise OSError("simulated write interruption")
        original(path, payload)

    monkeypatch.setattr(shadow_campaign, "_write_exclusive", interrupted_write)
    with pytest.raises(OSError, match="simulated write interruption"):
        run_shadow_day(
            plan,
            tmp_path / "shadow",
            campaign_id="atomic-recovery",
            signal_date=date(2026, 7, 15),
            shadow_model=model,
            generated_at=_AFTER_CLOSE,
            caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
                _plan, supplied, _response(rankings[0])
            ),
        )
    day_root = shadow_day_path(
        tmp_path / "shadow",
        campaign_id="atomic-recovery",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
    )
    assert not (day_root / "repetition-01").exists()
    stale = tmp_path / "shadow" / ".ai-stock-picker-shadow-staging" / "crashed-process"
    stale.mkdir()
    (stale / "partial").write_bytes(b"not published")

    monkeypatch.setattr(shadow_campaign, "_write_exclusive", original)
    recovered = finalize_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="atomic-recovery",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
    )
    assert recovered.repetition_statuses == (
        "tombstone",
        "tombstone",
        "tombstone",
    )
    assert validate_shadow_day(day_root)["consensus_status"] == "tombstone"


def test_repetition_validator_requires_owner_evidence_even_if_index_is_rewritten(
    tmp_path: Path,
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)
    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id="required-evidence",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings[0])
        ),
    )
    root = result.day_root / "repetition-01"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    (root / "prompt.txt").unlink()
    manifest["files"].pop("prompt.txt")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="file set"):
        validate_shadow_repetition(root)


@pytest.mark.parametrize("artifact", ["prompt.txt", "numeric_ranking.json"])
def test_repetition_validator_rebuilds_semantic_evidence_after_rehash(
    tmp_path: Path, artifact: str
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)
    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id=f"semantic-{artifact.split('.')[0]}",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings[0])
        ),
    )
    root = result.day_root / "repetition-01"
    path = root / artifact
    payload = b"tampered\n" if artifact == "prompt.txt" else b"{}\n"
    path.write_bytes(payload)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"][artifact] = {
        "sha256": sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    if artifact == "prompt.txt":
        manifest["prompt_sha256"] = sha256(payload).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate snapshot"):
        validate_shadow_repetition(root)


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        ("provider_request_body.json", "frozen prompt"),
        ("provider_response_body.bin", "raw response"),
    ],
)
def test_repetition_validator_rejects_rehashed_provider_semantic_drift(
    tmp_path: Path, artifact: str, message: str
) -> None:
    plan = _frozen_plan(tmp_path)
    model = ShadowModel(provider="openai", model="gpt-test")
    rankings = _rankings(plan)
    result = run_shadow_day(
        plan,
        tmp_path / "shadow",
        campaign_id=f"provider-{artifact.split('.')[0]}",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings[0])
        ),
    )
    root = result.day_root / "repetition-01"
    path = root / artifact
    payload = json.loads(path.read_bytes())
    if artifact == "provider_request_body.json":
        payload["input"] = "different prompt"
    else:
        payload["output"][0]["content"][0]["text"] = '{"picks":[]}'
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    path.write_bytes(encoded)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"][artifact] = {
        "sha256": sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        validate_shadow_repetition(root)


def test_campaign_validator_rejects_cross_date_model_parameter_drift(
    tmp_path: Path,
) -> None:
    model = ShadowModel(provider="openai", model="gpt-test")
    day_one = _frozen_plan(tmp_path / "day-one")
    rankings_one = _rankings(day_one)
    first = run_shadow_day(
        day_one,
        tmp_path / "shadow",
        campaign_id="fixed-model",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings_one[0])
        ),
    )
    day_two = _frozen_plan(tmp_path / "day-two", signal_date=date(2026, 7, 16))
    rankings_two = _rankings(day_two)
    run_shadow_day(
        day_two,
        tmp_path / "shadow",
        campaign_id="fixed-model",
        signal_date=date(2026, 7, 16),
        shadow_model=ShadowModel(
            provider="openai", model="gpt-test", max_output_tokens=4096
        ),
        generated_at=datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc),
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(rankings_two[0])
        ),
    )

    with pytest.raises(ValueError, match="parameters drifted"):
        validate_shadow_campaign(first.day_root.parents[1])


def test_campaign_validator_rejects_cross_date_style_drift(tmp_path: Path) -> None:
    model = ShadowModel(provider="openai", model="gpt-test")
    first_plan = _frozen_plan(tmp_path / "day-one")
    first_rankings = _rankings(first_plan)
    first = run_shadow_day(
        first_plan,
        tmp_path / "shadow",
        campaign_id="fixed-style",
        signal_date=date(2026, 7, 15),
        shadow_model=model,
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(first_rankings[0])
        ),
    )
    second_plan = _frozen_plan(
        tmp_path / "day-two",
        signal_date=date(2026, 7, 16),
        style="quality",
    )
    second_rankings = _rankings(second_plan)
    run_shadow_day(
        second_plan,
        tmp_path / "shadow",
        campaign_id="fixed-style",
        signal_date=date(2026, 7, 16),
        shadow_model=model,
        generated_at=datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc),
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(second_rankings[0])
        ),
    )

    with pytest.raises(ValueError, match="parameters drifted"):
        validate_shadow_campaign(first.day_root.parents[1])


def test_campaign_validator_requires_same_frozen_input_across_models(
    tmp_path: Path,
) -> None:
    first_plan = _frozen_plan(tmp_path / "first")
    first_rankings = _rankings(first_plan)
    first = run_shadow_day(
        first_plan,
        tmp_path / "shadow",
        campaign_id="same-input",
        signal_date=date(2026, 7, 15),
        shadow_model=ShadowModel(provider="openai", model="gpt-test"),
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(first_rankings[0])
        ),
    )
    second_plan = _frozen_plan(tmp_path / "second")
    candidate = second_plan.universe.path
    payload = json.loads(candidate.read_bytes())
    payload["candidate_universe"][0]["relevance"] = 0.01
    candidate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rebuilt = build_selection_plan(
        market="CN",
        candidates_path=candidate,
        as_of=date(2026, 7, 15),
        top_n=10,
        prompt_profile="bounded_ranking_v2",
    )
    second_root = write_pick_plan(rebuilt, tmp_path / "second-plan")
    second_plan = load_pick_plan(second_root / "plan.json")
    second_rankings = _rankings(second_plan)
    run_shadow_day(
        second_plan,
        tmp_path / "shadow",
        campaign_id="same-input",
        signal_date=date(2026, 7, 15),
        shadow_model=ShadowModel(provider="deepseek", model="deepseek-test"),
        generated_at=_AFTER_CLOSE,
        caller=lambda _plan, supplied, _repetition, _timeout: _exchange(
            _plan, supplied, _response(second_rankings[0])
        ),
    )

    with pytest.raises(ValueError, match="same frozen daily input"):
        validate_shadow_campaign(first.day_root.parents[1])
