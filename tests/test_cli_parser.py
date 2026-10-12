"""Public CLI argument and command-discovery contracts."""

from __future__ import annotations

import pytest

from stock_analysis.app.cli import create_parser, main


def test_root_help_lists_only_two_markets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "{us,cn}" in output
    assert "backtest" not in output
    assert "report" not in output
    assert "pipeline" not in output


def test_market_parsers_expose_documented_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for market in ("us", "cn"):
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args([market, "--help"])
        assert exit_info.value.code == 0
        help_text = capsys.readouterr().out
        for command in (
            "contract-info",
            "pick",
            "pick-plan",
            "validate",
            "validate-evidence",
            "stability-plan",
            "trial",
        ):
            assert command in help_text
        for command in (
            "shadow-decision-plan",
            "shadow-launch-receipt",
            "shadow-day",
            "shadow-watchdog",
            "validate-shadow-day",
            "validate-shadow-campaign",
        ):
            assert (command in help_text) == (market == "cn")
    for removed in ("backtest", "report", "pipeline"):
        with pytest.raises(SystemExit):
            parser.parse_args(["cn", removed])
