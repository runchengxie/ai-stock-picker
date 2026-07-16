from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from stock_analysis.ai_lab.providers import ProviderExchange
from stock_analysis.ai_lab.selection import (
    SelectionPlan,
    build_selection_plan,
    create_selection,
)
from stock_analysis.app.cli import app, create_parser, main


def _exchange(
    prompt: str, response: str, *, timeout: float = 120.0
) -> ProviderExchange:
    request = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode()
    raw_response = json.dumps(
        {
            "model": "deepseek-chat-20260715",
            "choices": [{"message": {"content": response}}],
        },
        ensure_ascii=False,
    ).encode()
    return ProviderExchange(
        provider="deepseek",
        model="deepseek-chat",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        request_method="POST",
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "<redacted>"),
        ),
        request_body=request,
        response_body=raw_response,
        response_text=response,
        actual_model="deepseek-chat-20260715",
        extraction_error=None,
        timeout_seconds=timeout,
    )


def _write_v2_selection(candidates: Path, destination: Path) -> dict[str, Any]:
    plan = build_selection_plan(
        market="CN",
        candidates_path=candidates,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        },
        ensure_ascii=False,
    )
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    payload = artifact.model_dump(mode="json")
    payload["prompt_version"] = "2026-07-15.2"
    payload["lineage"]["prompt_sha256"] = "a" * 64
    payload["picks"][0]["reasoning"] = (
        "候选特征显示高流动性、强趋势和多重主题支撑，质量较高。"
    )
    payload["picks"][0]["risk_note"] = "短期涨幅较大，需注意回调风险。"
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _tamper_v2_payload(payload: dict[str, Any], case: str) -> None:
    if case == "input_hash":
        payload["lineage"]["input_sha256"] = "0" * 64
    elif case == "membership":
        payload["picks"][0]["symbol"] = "601398.SH"
    elif case == "enrichment":
        payload["picks"][0]["name"] = "伪造银行"
    elif case == "url":
        payload["picks"][0]["reasoning"] = "候选特征详见 https://example.com。"
    elif case == "trading":
        payload["picks"][0]["reasoning"] = "候选特征支持建议买入并增配。"
    elif case == "provider":
        payload["picks"][0]["reasoning"] = "候选特征由供应商 DëepSeek 输出。"
    else:
        payload["picks"][0]["reasoning"] = "Candidate features support the rank."


def test_root_help_lists_only_two_markets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "{us,cn}" in output
    assert "backtest" not in output
    assert "report" not in output
    assert "pipeline" not in output


def test_market_parsers_expose_documented_commands() -> None:
    parser = create_parser()
    for market in ("us", "cn"):
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args([market, "--help"])
        assert exit_info.value.code == 0
    for removed in ("backtest", "report", "pipeline"):
        with pytest.raises(SystemExit):
            parser.parse_args(["cn", removed])


@pytest.mark.parametrize(
    ("market", "fixture_name", "style"),
    [("cn", "cn_manifest", "momentum"), ("us", "us_manifest", "growth")],
)
def test_dry_run_is_network_free_and_reports_hashes(
    market: str,
    fixture_name: str,
    style: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = request.getfixturevalue(fixture_name)
    assert isinstance(manifest, Path)
    code = main(
        [
            market,
            "pick",
            "--candidates",
            str(manifest),
            "--as-of",
            "20260715",
            "--top-n",
            "2",
            "--style",
            style,
            "--credential-file",
            str(tmp_path / "not-read-during-dry-run.env"),
            "--dry-run",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["market"] == market.upper()
    assert payload["as_of"] == "2026-07-15"
    assert payload["candidate_observation_date"] == "2026-07-14"
    expected_assurance = "signal_date_only" if market == "cn" else "unverified"
    assert payload["point_in_time_assurance"] == expected_assurance
    assert payload["eligible_as_oos_evidence"] is False
    assert payload["output"] is None
    assert len(payload["input_sha256"]) == 64
    assert len(payload["prompt_sha256"]) == 64


def test_live_path_writes_validated_artifact(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "依据 score 候选字段进行相对排序",
                    "risk_note": "仅依据 score，风险解读仍有信息边界",
                }
            ]
        }
    )
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda plan, **_kwargs: _exchange(plan.prompt, response),
    )
    output = tmp_path / "selection.json"
    code = main(
        [
            "cn",
            "pick",
            "--candidates",
            str(cn_manifest),
            "--output",
            str(output),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text())
    assert payload["picks"][0]["name"] == "浦发银行"
    assert payload["selection_as_of"] == "2026-07-15"
    assert payload["candidate_observation_date"] == "2026-07-14"
    assert payload["strict_point_in_time"] is False
    assert payload["eligible_as_oos_evidence"] is False
    assert "validated picks" in capsys.readouterr().out
    evidence = Path(f"{output}.evidence")
    assert (evidence / "manifest.json").is_file()
    assert (evidence / "prompt.txt").is_file()
    assert (evidence / "provider_response_body.bin").is_file()

    assert (
        main(
            [
                "cn",
                "validate",
                "--selection",
                str(output),
                "--candidates",
                str(cn_manifest),
                "--evidence-dir",
                str(evidence),
            ]
        )
        == 0
    )
    validation = json.loads(capsys.readouterr().out)
    assert validation == {
        "commentary_policy_revalidated": True,
        "market": "CN",
        "picks": 1,
        "prompt_hash_revalidated": True,
        "prompt_version": "2026-07-16.4",
        "response_sha256_verification": "byte_exact_evidence",
        "selection_as_of": "2026-07-15",
        "valid": True,
        "validation_profile": "current_full",
    }


def test_http_success_with_invalid_provider_body_is_archived_and_rejected(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_body = b"http-200-but-not-json"

    def invalid_exchange(plan: SelectionPlan, **_kwargs: object) -> ProviderExchange:
        return replace(
            _exchange(plan.prompt, "unused"),
            response_body=raw_body,
            response_text=None,
            actual_model=None,
            extraction_error="provider_response_invalid_json",
        )

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", invalid_exchange
    )
    output = tmp_path / "selection.json"
    evidence = tmp_path / "invalid-response-evidence"
    code = main(
        [
            "cn",
            "pick",
            "--candidates",
            str(cn_manifest),
            "--output",
            str(output),
            "--evidence-dir",
            str(evidence),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
        ]
    )

    assert code == 2
    assert not output.exists()
    assert (evidence / "provider_response_body.bin").read_bytes() == raw_body
    assert not (evidence / "model_response.txt").exists()
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["rejection"] == "provider_response_invalid_json"
    assert manifest["response_model"] is None
    assert "invalid response schema" in capsys.readouterr().err
    assert b"owner-secret" not in b"".join(
        path.read_bytes() for path in evidence.rglob("*") if path.is_file()
    )


def test_validate_rejects_market_mismatch(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        }
    )
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda plan, **_kwargs: _exchange(plan.prompt, response),
    )
    output = tmp_path / "cn-selection.json"
    assert (
        main(
            [
                "cn",
                "pick",
                "--candidates",
                str(cn_manifest),
                "--output",
                str(output),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "us",
                "validate",
                "--selection",
                str(output),
                "--candidates",
                str(cn_manifest),
            ]
        )
        == 2
    )
    assert "does not match CLI market" in capsys.readouterr().err


def test_validate_rechecks_commentary_and_candidate_lineage(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        }
    )
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda plan, **_kwargs: _exchange(plan.prompt, response),
    )
    output = tmp_path / "selection.json"
    assert (
        main(
            [
                "cn",
                "pick",
                "--candidates",
                str(cn_manifest),
                "--output",
                str(output),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    original = json.loads(output.read_text(encoding="utf-8"))
    cases = {
        "commentary": lambda payload: payload["picks"][0].update(
            reasoning="综合候选评分建议买入并访问 https://example.com。"
        ),
        "input-hash": lambda payload: payload["lineage"].update(input_sha256="0" * 64),
    }
    for name, tamper in cases.items():
        payload = json.loads(json.dumps(original))
        tamper(payload)
        tampered = tmp_path / f"tampered-{name}.json"
        tampered.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        assert (
            main(
                [
                    "cn",
                    "validate",
                    "--selection",
                    str(tampered),
                    "--candidates",
                    str(cn_manifest),
                ]
            )
            == 2
        )
        assert "aipick: error:" in capsys.readouterr().err


def test_validate_v2_uses_read_only_legacy_profile(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selection = tmp_path / "production-v2-selection.json"
    _write_v2_selection(cn_manifest, selection)
    original = selection.read_bytes()

    code = main(
        [
            "cn",
            "validate",
            "--selection",
            str(selection),
            "--candidates",
            str(cn_manifest),
        ]
    )

    assert code == 0
    assert selection.read_bytes() == original
    assert json.loads(capsys.readouterr().out) == {
        "commentary_policy_revalidated": False,
        "market": "CN",
        "picks": 1,
        "prompt_hash_revalidated": False,
        "prompt_version": "2026-07-15.2",
        "response_sha256_verification": "format_only_raw_response_unavailable",
        "selection_as_of": "2026-07-15",
        "valid": True,
        "validation_profile": "legacy_read_only",
    }


@pytest.mark.parametrize(
    "case",
    [
        "input_hash",
        "membership",
        "enrichment",
        "url",
        "trading",
        "provider",
        "language",
    ],
)
def test_validate_v2_rejects_candidate_or_commentary_mutations(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    selection = tmp_path / f"tampered-v2-{case}.json"
    payload = _write_v2_selection(cn_manifest, selection)
    _tamper_v2_payload(payload, case)
    selection.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code = main(
        [
            "cn",
            "validate",
            "--selection",
            str(selection),
            "--candidates",
            str(cn_manifest),
        ]
    )

    assert code == 2
    assert "aipick: error:" in capsys.readouterr().err


def test_live_path_requires_output(
    cn_manifest: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "cn",
            "pick",
            "--candidates",
            str(cn_manifest),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
        ]
    )
    assert code == 2
    assert "--output is required" in capsys.readouterr().err


def test_stability_plan_is_network_free_and_trial_uses_frozen_prompt(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("stability planning must not call a provider")

    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange", unexpected_call
    )
    campaign = tmp_path / "campaign"
    assert (
        main(
            [
                "cn",
                "stability-plan",
                "--candidates",
                str(cn_manifest),
                "--as-of",
                "2026-07-15",
                "--top-n",
                "1",
                "--style",
                "momentum",
                "--campaign-id",
                "deepseek-stability-v2",
                "--output-dir",
                str(campaign),
            ]
        )
        == 0
    )
    assert "api_calls=0" in capsys.readouterr().out

    trial = campaign / "trials/canonical/trial.json"
    frozen_prompt = (trial.parent / "prompt.txt").read_text(encoding="utf-8")
    first_symbol = json.loads(frozen_prompt)["candidates"][0]["symbol"]
    response = _response_for_prompt(first_symbol)
    monkeypatch.setattr(
        "stock_analysis.app.cli.call_plan_provider_exchange",
        lambda plan, **_kwargs: _exchange(plan.prompt, response),
    )
    output = tmp_path / "trial-selection.json"
    assert (
        main(
            [
                "cn",
                "trial",
                "--plan",
                str(trial),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.is_file()


def _response_for_prompt(symbol: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": "综合候选评分支持该候选排序。",
                    "risk_note": "综合候选评分仍有信息边界。",
                }
            ]
        },
        ensure_ascii=False,
    )


def test_live_path_refuses_existing_output_before_provider_call(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "selection.json"
    output.write_text("existing receipt\n", encoding="utf-8")

    def unexpected_call(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek", unexpected_call
    )
    code = main(
        [
            "cn",
            "pick",
            "--candidates",
            str(cn_manifest),
            "--output",
            str(output),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
        ]
    )

    assert code == 2
    assert "already exists" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "existing receipt\n"


@pytest.mark.parametrize(
    ("credential_name", "credential_payload"),
    [
        (
            "owner.env",
            "GEMINI_API_KEY=must-not-be-used\nDEEPSEEK_API_KEY=owner-key\n",
        ),
        (
            "api_keys.json",
            json.dumps(
                {
                    "ai_stock_picker": {
                        "gemini": {"api_key": "must-not-be-used"},
                        "deepseek": {"api_key": "owner-key"},
                    }
                }
            ),
        ),
    ],
)
def test_live_path_uses_market_specific_key_from_credential_file(
    cn_manifest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    credential_name: str,
    credential_payload: str,
) -> None:
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "依据 score 候选字段进行相对排序",
                    "risk_note": "仅依据 score，风险解读仍有信息边界",
                }
            ]
        }
    )
    credential_file = tmp_path / credential_name
    credential_file.write_text(credential_payload, encoding="utf-8")
    credential_file.chmod(0o600)
    observed: list[str | None] = []

    def fake_deepseek(
        prompt: str,
        *,
        model: str,
        timeout: float,
        api_key: str | None = None,
    ) -> ProviderExchange:
        del model
        observed.append(api_key)
        return _exchange(prompt, response, timeout=timeout)

    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek_exchange", fake_deepseek
    )
    output = tmp_path / "selection.json"

    code = main(
        [
            "cn",
            "pick",
            "--candidates",
            str(cn_manifest),
            "--output",
            str(output),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
            "--credential-file",
            str(credential_file),
        ]
    )

    assert code == 0
    assert observed == ["owner-key"]
    assert output.is_file()


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "cn",
            "pick",
            "--candidates",
            "missing",
            "--output",
            "x",
            "--as-of",
            "bad",
            "--top-n",
            "1",
        ],
        [
            "cn",
            "pick",
            "--candidates",
            "missing",
            "--output",
            "x",
            "--as-of",
            "20260715",
            "--top-n",
            "1",
            "--timeout",
            "0",
        ],
        [
            "cn",
            "pick",
            "--candidates",
            "missing",
            "--output",
            "x",
            "--as-of",
            "20260715",
            "--top-n",
            "1",
            "--timeout",
            "nan",
        ],
    ],
)
def test_cli_reports_validation_errors_without_traceback(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == 2
    error = capsys.readouterr().err
    assert error.startswith("aipick: error:")
    assert "Traceback" not in error


def test_console_entrypoint_exits_with_main_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["aipick"])
    with pytest.raises(SystemExit) as exit_info:
        app()
    assert exit_info.value.code == 0
