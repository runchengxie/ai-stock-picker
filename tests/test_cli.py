from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_stock_picker.cli import app, create_parser, main
from ai_stock_picker.selection import create_selection


def _provider_response() -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": "AAPL",
                    "confidence_score": 8,
                    "reasoning": (
                        "The overall candidate score supports the relative ranking."
                    ),
                    "risk_note": (
                        "The overall candidate score is the only supplied basis for "
                        "this risk note."
                    ),
                }
            ]
        }
    )


def test_root_help_is_market_neutral(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "pick" in output
    assert "validate" in output
    assert "migrate-csv" in output
    assert "cn" not in output.lower()


def test_pick_parser_has_no_market_subcommand() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "pick",
            "--candidates",
            "x.json",
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
            "--style",
            "quality",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
            "--dry-run",
        ]
    )
    assert args.command == "pick"


def test_dry_run_derives_market_without_reading_credentials(
    us_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_credentials = tmp_path / "missing.env"
    code = main(
        [
            "pick",
            "--candidates",
            str(us_manifest),
            "--as-of",
            "20260715",
            "--top-n",
            "2",
            "--style",
            "growth",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
            "--credential-file",
            str(missing_credentials),
            "--dry-run",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["market"] == "US"
    assert payload["provider"] == "deepseek"
    assert payload["output"] is None
    assert len(payload["prompt_sha256"]) == 64


def test_live_path_requires_output(
    us_manifest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "pick",
            "--candidates",
            str(us_manifest),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
            "--style",
            "quality",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
        ]
    )
    assert code == 2
    assert "--output is required" in capsys.readouterr().err


def test_live_path_writes_artifact(
    us_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _provider_response()
    monkeypatch.setattr(
        "ai_stock_picker.cli.run_selection",
        lambda plan, timeout, credential_file=None: create_selection(
            plan,
            response,
            generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
        ),
    )
    output = tmp_path / "selection.json"
    code = main(
        [
            "pick",
            "--candidates",
            str(us_manifest),
            "--output",
            str(output),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
            "--style",
            "quality",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text())
    assert payload["provider"] == "deepseek"
    assert "generation_trace" in payload
    assert "validated picks" in capsys.readouterr().out


def test_validate_command_rechecks_artifact(
    us_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ai_stock_picker.selection import build_selection_plan

    plan = build_selection_plan(
        candidates_path=us_manifest,
        as_of=datetime(2026, 7, 15).date(),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    artifact = create_selection(
        plan,
        _provider_response(),
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )
    selection = tmp_path / "selection.json"
    selection.write_text(artifact.model_dump_json(), encoding="utf-8")
    code = main(
        [
            "validate",
            "--selection",
            str(selection),
            "--candidates",
            str(us_manifest),
        ]
    )
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["validation_profile"] == "current_full"


def test_existing_output_fails_before_provider(
    us_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "selection.json"
    output.write_text("existing\n", encoding="utf-8")

    def unexpected(*args: object, **kwargs: object) -> str:
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("ai_stock_picker.selection.call_provider", unexpected)
    code = main(
        [
            "pick",
            "--candidates",
            str(us_manifest),
            "--output",
            str(output),
            "--as-of",
            "2026-07-15",
            "--top-n",
            "1",
            "--style",
            "quality",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
        ]
    )
    assert code == 2
    assert "already exists" in capsys.readouterr().err


def test_migrate_csv_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "legacy.csv"
    source.write_text("ticker,company_name,score\nAAPL,Apple,9\n", encoding="utf-8")
    output = tmp_path / "manifest.json"
    code = main(
        [
            "migrate-csv",
            "--input",
            str(source),
            "--output",
            str(output),
            "--market",
            "US",
            "--observation-date",
            "2026-07-14",
            "--generated-at",
            "2026-07-15T00:00:00+00:00",
            "--data-cutoff",
            "2026-07-14",
        ]
    )
    assert code == 0
    assert json.loads(output.read_text())["market"] == "US"
    assert "versioned candidate manifest" in capsys.readouterr().out


def test_cli_errors_have_no_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "pick",
            "--candidates",
            "missing.json",
            "--as-of",
            "bad",
            "--top-n",
            "1",
            "--style",
            "quality",
            "--response-language",
            "en",
            "--provider",
            "deepseek",
            "--dry-run",
        ]
    )
    assert code == 2
    error = capsys.readouterr().err
    assert error.startswith("aipick: error:")
    assert "Traceback" not in error


def test_console_entrypoint_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["aipick"])
    with pytest.raises(SystemExit) as exc:
        app()
    assert exc.value.code == 0
