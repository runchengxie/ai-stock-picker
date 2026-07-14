from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from stock_analysis.ai_lab.contracts import SelectionArtifact
from stock_analysis.ai_lab.selection import (
    build_selection_plan,
    call_plan_provider,
    create_selection,
    run_selection,
    write_selection,
)


def _response(*symbols: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 9 - index,
                    "reasoning": f"Evidence for {symbol}",
                    "risk_note": f"Risk for {symbol}",
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
    assert plan.model == "deepseek-chat"
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
    assert "supported growth signals" in growth.prompt


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
    assert artifact.input_count == 3
    assert artifact.requested_top_n == 2
    assert [pick.symbol for pick in artifact.picks] == ["000001.SZ", "600000.SH"]
    assert [pick.name for pick in artifact.picks] == ["平安银行", "浦发银行"]
    assert [pick.topic for pick in artifact.picks] == ["金融科技", "银行"]
    assert artifact.lineage.input_sha256 == plan.universe.input_sha256
    assert len(artifact.lineage.prompt_sha256) == 64
    assert len(artifact.lineage.response_sha256) == 64


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
        _response("AAPL"),
        generated_at=datetime(2026, 7, 16, 0, 30, tzinfo=timezone.utc),
    )
    assert artifact.temporal_status == "contemporaneous"
    assert artifact.point_in_time_assurance == "unverified"
    assert artifact.generated_at.tzinfo == timezone.utc


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
    assert observed == [(plan.prompt, "deepseek-chat", 3.5)]


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
        lambda prompt, *, model, timeout: f"cn:{model}:{timeout}:{len(prompt)}",
    )
    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_gemini",
        lambda prompt, *, model, timeout: f"us:{model}:{timeout}:{len(prompt)}",
    )
    assert call_plan_provider(cn, timeout=2).startswith("cn:deepseek-chat:2")
    assert call_plan_provider(us, timeout=4).startswith("us:gemini-2.5-flash:4")
