from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from stock_analysis.ai_lab.alias_contracts import alias_maps_sha256
from stock_analysis.ai_lab.evidence import (
    validate_selection_evidence,
    write_selection_evidence,
)
from stock_analysis.ai_lab.evidence_consistency import provider_parameters
from stock_analysis.ai_lab.frozen_plan import load_pick_plan
from stock_analysis.ai_lab.providers import DEEPSEEK_SYSTEM_MESSAGE, ProviderExchange
from stock_analysis.ai_lab.selection import build_selection_plan, create_selection
from stock_analysis.app.cli import main


def _aliases() -> tuple[dict[str, str], dict[str, str]]:
    return (
        {"600000.SH": "C001", "000001.SZ": "C002", "430047.BJ": "C003"},
        {
            "600000.SH": "候选甲",
            "000001.SZ": "候选乙",
            "430047.BJ": "候选丙",
        },
    )


def _response(symbol: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选的相对排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        },
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


def test_alias_maps_sha256_has_fixed_cross_repository_digest() -> None:
    assert (
        alias_maps_sha256(
            {"600000.SH": "C001", "000001.SZ": "C002"},
            {"600000.SH": "候选甲", "000001.SZ": "候选乙"},
        )
        == "509cb9bdd694127494958d7cddb4aa4e182c5532b208683272a6f169802bc542"
    )


def test_cli_pick_plan_freezes_opaque_alias_files(
    cn_manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symbol_aliases, name_aliases = _aliases()
    symbol_path = tmp_path / "symbols.json"
    name_path = tmp_path / "names.json"
    symbol_path.write_text(json.dumps(symbol_aliases), encoding="utf-8")
    name_path.write_text(json.dumps(name_aliases, ensure_ascii=False), encoding="utf-8")

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("pick-plan must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    root = tmp_path / "opaque-plan"
    assert (
        main(
            [
                "cn",
                "pick-plan",
                "--candidates",
                str(cn_manifest),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
                "--symbol-aliases-file",
                str(symbol_path),
                "--name-aliases-file",
                str(name_path),
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )
    rebuilt = load_pick_plan(root / "plan.json")
    assert dict(rebuilt.symbol_aliases) == symbol_aliases
    assert dict(rebuilt.name_aliases) == name_aliases


def test_cli_pick_plan_rejects_invalid_or_unpaired_alias_files(
    cn_manifest: Path, tmp_path: Path
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"600000.SH": 1}), encoding="utf-8")
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_aliases()[1]), encoding="utf-8")
    common = [
        "cn",
        "pick-plan",
        "--candidates",
        str(cn_manifest),
        "--as-of",
        "2026-07-15",
        "--top-n",
        "1",
        "--output-dir",
        str(tmp_path / "invalid-plan"),
    ]
    assert main([*common, "--symbol-aliases-file", str(invalid)]) == 2
    assert (
        main(
            [
                *common,
                "--symbol-aliases-file",
                str(invalid),
                "--name-aliases-file",
                str(valid),
            ]
        )
        == 2
    )


def test_opaque_selection_evidence_binds_alias_mapping_hash(
    cn_manifest: Path, tmp_path: Path
) -> None:
    symbol_aliases, name_aliases = _aliases()
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
        symbol_aliases=symbol_aliases,
        name_aliases=name_aliases,
    )
    response = _response(symbol_aliases["600000.SH"])
    generated_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    artifact = create_selection(plan, response, generated_at=generated_at)
    output = write_selection_evidence(
        plan,
        _exchange(plan, response),
        artifact,
        tmp_path / "opaque-evidence",
    )
    manifest = validate_selection_evidence(output)
    assert manifest["symbol_aliases"] == symbol_aliases
    assert manifest["name_aliases"] == name_aliases
    assert manifest["alias_maps_sha256"] == alias_maps_sha256(
        symbol_aliases, name_aliases
    )
    selection = output / "selection.json"
    base_args = [
        "cn",
        "validate",
        "--selection",
        str(selection),
        "--candidates",
        str(cn_manifest),
    ]
    assert main(base_args) == 2
    assert main([*base_args, "--evidence-dir", str(output)]) == 0
