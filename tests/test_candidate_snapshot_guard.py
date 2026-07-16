from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from stock_analysis.ai_lab.selection import (
    build_selection_plan,
    call_plan_provider_exchange,
    run_selection,
)


def _response(symbol: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选的相对排序。",
                    "risk_note": "仅依据综合候选评分，风险解读仍有信息边界。",
                }
            ]
        },
        ensure_ascii=False,
    )


def test_run_selection_checks_candidate_before_injected_call(
    cn_manifest: Path,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    cn_manifest.write_bytes(cn_manifest.read_bytes() + b"\n")
    called = False

    def caller(_prompt: str, _model: str, _timeout: float) -> str:
        nonlocal called
        called = True
        return _response("600000.SH")

    with pytest.raises(ValueError, match="candidate input changed"):
        run_selection(plan, caller=caller)

    assert not called


def test_exchange_call_checks_candidate_before_network(
    cn_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    cn_manifest.write_bytes(cn_manifest.read_bytes() + b"\n")
    called = False

    def provider(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek_exchange", provider
    )

    with pytest.raises(ValueError, match="candidate input changed"):
        call_plan_provider_exchange(plan)

    assert not called
