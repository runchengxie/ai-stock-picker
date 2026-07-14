from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from stock_analysis.app.cli import app, create_parser, main


def test_root_help_lists_only_two_markets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "{us,cn}" in output
    assert "backtest" not in output
    assert "report" not in output
    assert "pipeline" not in output


def test_market_parsers_expose_only_pick() -> None:
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
    output = tmp_path / "must-not-exist.json"
    code = main(
        [
            market,
            "pick",
            "--candidates",
            str(manifest),
            "--output",
            str(output),
            "--as-of",
            "20260715",
            "--top-n",
            "2",
            "--style",
            style,
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
    assert len(payload["input_sha256"]) == 64
    assert len(payload["prompt_sha256"]) == 64
    assert not output.exists()


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
                    "reasoning": "supplied evidence",
                    "risk_note": "supplied risk",
                }
            ]
        }
    )
    monkeypatch.setattr(
        "stock_analysis.ai_lab.selection.call_deepseek",
        lambda prompt, *, model, timeout: response,
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
    "arguments",
    [
        ["cn", "pick", "--candidates", "missing", "--output", "x", "--as-of", "bad"],
        [
            "cn",
            "pick",
            "--candidates",
            "missing",
            "--output",
            "x",
            "--as-of",
            "20260715",
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
