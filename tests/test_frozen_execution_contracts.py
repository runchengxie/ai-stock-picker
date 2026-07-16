from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from stock_analysis.ai_lab.frozen_plan import write_pick_plan
from stock_analysis.ai_lab.providers import (
    DEEPSEEK_SYSTEM_MESSAGE,
    ProviderExchange,
    call_deepseek_exchange,
)
from stock_analysis.ai_lab.selection import (
    build_selection_plan,
    call_plan_provider_exchange,
)
from stock_analysis.app.cli import main


def test_legacy_v1_dispatch_preserves_exact_historical_request(
    cn_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        model="deepseek-chat",
        provider_parameter_schema="legacy_v1",
        prompt_profile="legacy_stability_v3",
    )

    def transport(_request: Any, _timeout: float) -> bytes:
        return b'{"model":"deepseek-chat","choices":[{"message":{"content":"{}"}}]}'

    def captured_call(prompt: str, **kwargs: Any) -> ProviderExchange:
        return call_deepseek_exchange(
            prompt,
            model=cast(str, kwargs["model"]),
            thinking=kwargs["thinking"],
            reasoning_effort=kwargs["reasoning_effort"],
            max_tokens=kwargs["max_tokens"],
            parameter_schema=kwargs["parameter_schema"],
            timeout=kwargs["timeout"],
            transport=transport,
            api_key="owner-key",
        )

    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek_exchange", captured_call
    )
    exchange = call_plan_provider_exchange(plan, timeout=17)
    expected = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_MESSAGE},
            {"role": "user", "content": plan.prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    assert exchange.request_body == json.dumps(expected, ensure_ascii=False).encode()
    assert set(json.loads(exchange.request_body)) == {
        "model",
        "messages",
        "temperature",
        "response_format",
    }


@pytest.mark.parametrize("layout", ["equal", "output_inside_evidence"])
def test_cli_rejects_output_and_evidence_overlap_before_provider_call(
    layout: str,
    cn_manifest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = tmp_path / "shared"
    output = shared if layout == "equal" else shared / "selection.json"

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("overlapping paths must fail before the provider call")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    assert (
        main(
            [
                "cn",
                "pick",
                "--candidates",
                str(cn_manifest),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
                "--output",
                str(output),
                "--evidence-dir",
                str(shared),
            ]
        )
        == 2
    )


def test_cli_rejects_evidence_inside_frozen_plan_before_provider_call(
    cn_manifest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("overlapping paths must fail before the provider call")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    assert (
        main(
            [
                "cn",
                "trial",
                "--plan",
                str(root / "plan.json"),
                "--output",
                str(tmp_path / "selection.json"),
                "--evidence-dir",
                str(root / "evidence"),
            ]
        )
        == 2
    )


def test_cli_trial_rejects_symlinked_plan_before_provider_call(
    cn_manifest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    root = write_pick_plan(plan, tmp_path / "frozen")
    link = tmp_path / "plan-link.json"
    link.symlink_to(root / "plan.json")

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unsafe plan paths must fail before the provider call")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    assert (
        main(
            [
                "cn",
                "trial",
                "--plan",
                str(link),
                "--output",
                str(tmp_path / "selection.json"),
            ]
        )
        == 2
    )
