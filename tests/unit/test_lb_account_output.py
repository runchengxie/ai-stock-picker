"""
Tests for LongPort Account Overview Output (REAL-only)

Updated to real-only mode:
- The `lb-account` command no longer accepts the --env parameter.
- It now defaults to displaying real account data; preview/execution logic is handled by other commands.
These tests verify the rendered output by patching `get_account_snapshot` to return a constructed snapshot.
"""

import json
import logging
from unittest.mock import patch

import pytest

from stock_analysis import cli
from stock_analysis.shared.models import AccountSnapshot, Position


def make_snapshot(
    cash: float, positions: list[tuple[str, int, float]]
) -> AccountSnapshot:
    """Helper function to create an AccountSnapshot object for testing."""
    pos = [
        Position(symbol=s, quantity=q, last_price=p, estimated_value=q * p, env="real")
        for s, q, p in positions
    ]
    return AccountSnapshot(env="real", cash_usd=cash, positions=pos)


@pytest.mark.unit
class TestLBAccountTableOutput:
    """Tests for the table format output of the lb-account command."""

    def test_lb_account_prints_positions_table(self, capsys):
        """Test that the command prints both cash and positions in a table."""
        snap = make_snapshot(1234.56, [("AAPL.US", 10, 199.99)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            assert (
                cli.run_lb_account(only_funds=False, only_positions=False, fmt="table")
                == 0
            )

        out = capsys.readouterr().out
        # Check for headers for both cash and positions sections, and the specific stock symbol
        assert "Cash" in out and "Positions" in out and "AAPL.US" in out

    def test_table_output_with_funds_and_positions(self, capsys):
        """Test the table output with both funds and multiple positions."""
        snap = make_snapshot(5000.0, [("AAPL.US", 10, 150.0), ("MSFT.US", 5, 300.0)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(
                only_funds=False, only_positions=False, fmt="table"
            )

        assert result == 0
        out = capsys.readouterr().out
        assert "Cash (USD): $5,000.00" in out
        assert "AAPL.US" in out and "MSFT.US" in out
        assert "150.00" in out and "300.00" in out

    def test_table_output_only_funds(self, capsys):
        """Test that only the cash balance is shown when --only-funds is used."""
        snap = make_snapshot(2500.75, [("AAPL.US", 10, 150.0)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(
                only_funds=True, only_positions=False, fmt="table"
            )

        assert result == 0
        out = capsys.readouterr().out
        assert "Cash (USD): $2,500.75" in out
        # Ensure the positions table is not printed
        assert "Symbol" not in out and "AAPL.US" not in out

    def test_table_output_only_positions(self, capsys):
        """Test that only the positions table is shown when --only-positions is used."""
        snap = make_snapshot(1000.0, [("GOOGL.US", 2, 2500.0), ("AMZN.US", 1, 3000.0)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(
                only_funds=False, only_positions=True, fmt="table"
            )

        assert result == 0
        out = capsys.readouterr().out
        # Ensure the cash balance is not printed
        assert "Cash (USD)" not in out
        assert "GOOGL.US" in out and "AMZN.US" in out
        assert "2500.00" in out and "3000.00" in out

    def test_table_output_no_positions(self, capsys):
        """Test the output when the account has cash but no positions."""
        snap = make_snapshot(1000.0, [])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(
                only_funds=False, only_positions=False, fmt="table"
            )

        assert result == 0
        out = capsys.readouterr().out
        assert "No positions held" in out


@pytest.mark.unit
class TestLBAccountJsonOutput:
    """Tests for the JSON format output of the lb-account command."""

    def test_json_output_single_env(self, capsys):
        """Test that the command produces valid JSON output for the account snapshot."""
        snap = make_snapshot(1500.5, [("AAPL.US", 10, 150.05)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(fmt="json")

        assert result == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["env"] == "real"
        assert data[0]["cash_usd"] == 1500.5
        assert data[0]["positions"][0]["symbol"] == "AAPL.US"


@pytest.mark.unit
class TestLBAccountErrorHandling:
    """Tests for error handling scenarios."""

    def test_import_error_handling(self, caplog):
        """Test the error message when the 'longport' dependency is not installed."""
        with patch(
            "builtins.__import__", side_effect=ImportError("No module named 'longport'")
        ):
            with caplog.at_level(logging.ERROR):
                result = cli.run_lb_account()

        assert result == 1
        assert "Failed to import LongPort module" in caplog.text
        assert "pip install longport" in caplog.text

    def test_client_connection_error(self, capsys):
        """Test the error message for a generic client connection failure."""
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            side_effect=Exception("Connection failed"),
        ):
            result = cli.run_lb_account(fmt="table")

        assert result == 1
        err = capsys.readouterr().err
        assert "Failed to get account overview" in err

    def test_portfolio_snapshot_error_no_fallback(self, capsys):
        """Test that an API error during snapshot fetching is handled correctly."""
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            side_effect=Exception("API Error"),
        ):
            result = cli.run_lb_account(fmt="json")

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to get account overview" in captured.err


@pytest.mark.unit
class TestLBAccountParameterValidation:
    """Tests for parameter validation and behavior."""

    def test_format_parameter_validation(self, capsys):
        """Test that an invalid format falls back to the default 'table' format."""
        snap = make_snapshot(1000.0, [])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            result = cli.run_lb_account(fmt="xml") # 'xml' is not a supported format

        assert result == 0
        out = capsys.readouterr().out
        # Should default to table format
        assert "Cash (USD)" in out
        # Should not be JSON format
        assert "{" not in out

    def test_conflicting_flags(self, capsys):
        """Test the behavior with conflicting flags (--only-funds and --only-positions)."""
        snap = make_snapshot(1000.0, [("AAPL.US", 10, 150.0)])
        with patch(
            "stock_analysis.app.commands.lb_account.get_account_snapshot",
            return_value=snap,
        ):
            # When both flags are true, --only-funds should take precedence
            result = cli.run_lb_account(
                only_funds=True, only_positions=True, fmt="table"
            )

        assert result == 0
        out = capsys.readouterr().out
        assert "Cash (USD)" in out
        assert "Symbol" not in out
        assert "AAPL.US" not in out