"""Tests for the configuration reading module.

This file tests the configuration reading logic in utils/config.py, including:
- Time period calculation for period_mode=fixed/dynamic.
- Handling of date strings and date objects.
- Logic for buffer months/days.
- Two configuration formats for initial cash: unified vs. per-strategy.
"""

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from dateutil.relativedelta import relativedelta

from stock_analysis.shared.config import (
    ReportSettings,
    get_backtest_period,
    get_initial_cash,
    get_report_settings,
    load_cfg,
)


class TestLoadCfg:
    """Tests for loading configuration files."""

    def test_load_cfg_with_config_dir_yaml(self, tmp_path):
        """Test that config/config.yaml is read with priority."""
        # Create a temporary configuration file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"

        config_data = {
            "backtest": {
                "period_mode": "fixed",
                "start": "2021-01-01",
                "end": "2023-12-31",
                "initial_cash": 500000,
            }
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        # Mock the project root directory
        with patch("stock_analysis.shared.config.Path") as mock_path:
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                tmp_path,
            ]

            config = load_cfg()
            assert config["backtest"]["period_mode"] == "fixed"
            assert config["backtest"]["initial_cash"] == 500000

    def test_load_cfg_fallback_to_root_yaml(self, tmp_path):
        """Test fallback to config.yaml in the project root."""
        # Create a configuration file only in the project root
        config_file = tmp_path / "config.yaml"

        config_data = {
            "backtest": {
                "period_mode": "dynamic",
                "buffer": {"months": 6, "days": 15},
                "initial_cash": {"ai": 800000, "spy": 200000},
            }
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        with patch("stock_analysis.shared.config.Path") as mock_path:
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                tmp_path,
            ]

            config = load_cfg()
            assert config["backtest"]["period_mode"] == "dynamic"
            assert config["backtest"]["buffer"]["months"] == 6

    def test_load_cfg_no_config_file(self):
        """Test using default configuration when no config file is found."""
        with patch("stock_analysis.shared.config.Path") as mock_path:
            # Mock a non-existent path
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                Path("/nonexistent"),
            ]

            config = load_cfg()
            assert config["backtest"]["period_mode"] == "dynamic"
            assert config["backtest"]["buffer"]["months"] == 3
            assert config["backtest"]["buffer"]["days"] == 10
            assert config["backtest"]["initial_cash"] == 1000000

    def test_load_cfg_yaml_parse_error(self, tmp_path):
        """Test graceful degradation when a YAML parsing error occurs."""
        config_file = tmp_path / "config.yaml"

        # Write invalid YAML content
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: content: [")

        with patch("stock_analysis.shared.config.Path") as mock_path:
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                tmp_path,
            ]

            config = load_cfg()
            # It should return the default configuration
            assert config["backtest"]["period_mode"] == "dynamic"
            assert isinstance(config["backtest"]["initial_cash"], dict)


class TestGetBacktestPeriod:
    """Tests for backtest period calculation."""

    def test_fixed_mode_with_string_dates(self):
        """Test parsing string dates in fixed mode."""
        config_data = {
            "backtest": {
                "period_mode": "fixed",
                "start": "2021-04-02",
                "end": "2025-07-02",
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            start, end = get_backtest_period()

            assert start == datetime.date(2021, 4, 2)
            assert end == datetime.date(2025, 7, 2)

    def test_fixed_mode_with_date_objects(self):
        """Test handling of date objects in fixed mode."""
        config_data = {
            "backtest": {
                "period_mode": "fixed",
                "start": datetime.date(2020, 1, 1),
                "end": datetime.date(2024, 12, 31),
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            start, end = get_backtest_period()

            assert start == datetime.date(2020, 1, 1)
            assert end == datetime.date(2024, 12, 31)

    def test_dynamic_mode_with_buffer(self):
        """Test buffer time calculation in dynamic mode."""
        config_data = {
            "backtest": {"period_mode": "dynamic", "buffer": {"months": 3, "days": 10}}
        }

        # Mock portfolio data
        portfolios = {
            datetime.date(2022, 1, 1): ["AAPL", "MSFT"],
            datetime.date(2022, 4, 1): ["GOOGL", "TSLA"],
            datetime.date(2022, 7, 1): ["AMZN", "META"],
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            start, end = get_backtest_period(portfolios)

            assert start == datetime.date(2022, 1, 1)
            expected_end = datetime.date(2022, 7, 1) + relativedelta(months=3, days=10)
            assert end == expected_end

    def test_dynamic_mode_without_portfolios(self):
        """Test exception when portfolio data is missing in dynamic mode."""
        config_data = {"backtest": {"period_mode": "dynamic"}}

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            with pytest.raises(
                ValueError, match="Dynamic mode requires portfolios data"
            ):
                get_backtest_period()

    def test_dynamic_mode_default_buffer(self):
        """Test default buffer time in dynamic mode."""
        config_data = {
            "backtest": {
                "period_mode": "dynamic"
                # No buffer is configured, so default values should be used.
            }
        }

        portfolios = {datetime.date(2023, 1, 15): ["SPY"]}

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            start, end = get_backtest_period(portfolios)

            assert start == datetime.date(2023, 1, 15)
            expected_end = datetime.date(2023, 1, 15) + relativedelta(months=3, days=10)
            assert end == expected_end


class TestGetInitialCash:
    """Tests for getting initial cash."""

    def test_unified_cash_format(self):
        """Test the unified cash format."""
        config_data = {"backtest": {"initial_cash": 1500000}}

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            assert get_initial_cash("ai") == 1500000.0
            assert get_initial_cash("quant") == 1500000.0
            assert get_initial_cash("spy") == 1500000.0

    def test_strategy_specific_cash_format(self):
        """Test the per-strategy cash format."""
        config_data = {
            "backtest": {
                "initial_cash": {"ai": 2000000, "quant": 1500000, "spy": 500000}
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            assert get_initial_cash("ai") == 2000000.0
            assert get_initial_cash("quant") == 1500000.0
            assert get_initial_cash("spy") == 500000.0

    def test_strategy_specific_with_missing_strategy(self):
        """Test the default value when a specific strategy is missing in the per-strategy format."""
        config_data = {
            "backtest": {
                "initial_cash": {
                    "ai": 2000000,
                    "spy": 500000,
                    # The "quant" strategy is missing
                }
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            assert get_initial_cash("ai") == 2000000.0
            assert get_initial_cash("quant") == 1000000.0  # Default value
            assert get_initial_cash("spy") == 500000.0

    def test_no_initial_cash_config(self):
        """Test the default value when initial_cash is not configured."""
        config_data = {
            "backtest": {
                "period_mode": "fixed"
                # No initial_cash configuration
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            assert get_initial_cash("ai") == 1000000.0
            assert get_initial_cash("quant") == 1000000.0
            assert get_initial_cash("spy") == 1000000.0


class TestConfigIntegration:
    """Integration tests using realistic configuration file formats."""

    def test_real_config_format_fixed_mode(self, tmp_path):
        """Test a realistic configuration file format - fixed mode."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"

        # Use a realistic format similar to template.yaml
        config_content = """
backtest:
  period_mode: fixed
  start: 2021-04-02
  end: 2025-07-02
  buffer:
    months: 3
    days: 10
  initial_cash: 1000000
"""

        with open(config_file, "w", encoding="utf-8") as f:
            f.write(config_content)

        with patch("stock_analysis.shared.config.Path") as mock_path:
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                tmp_path,
            ]

            # Test the time period
            start, end = get_backtest_period()
            assert start == datetime.date(2021, 4, 2)
            assert end == datetime.date(2025, 7, 2)

            # Test unified cash
            assert get_initial_cash("ai") == 1000000.0
            assert get_initial_cash("spy") == 1000000.0

    def test_real_config_format_dynamic_mode(self, tmp_path):
        """Test a realistic configuration file format - dynamic mode."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"

        config_content = """
backtest:
  period_mode: dynamic
  buffer:
    months: 6
    days: 15
  initial_cash:
    ai: 1000000
    quant: 1000000
    spy: 1000000
"""

        with open(config_file, "w", encoding="utf-8") as f:
            f.write(config_content)

        with patch("stock_analysis.shared.config.Path") as mock_path:
            mock_path(__file__).resolve.return_value.parents = [
                None,
                None,
                None,
                tmp_path,
            ]

            # Test dynamic time period
            portfolios = {
                datetime.date(2022, 3, 1): ["AAPL"],
                datetime.date(2022, 9, 1): ["MSFT"],
            }

            start, end = get_backtest_period(portfolios)
            assert start == datetime.date(2022, 3, 1)
            expected_end = datetime.date(2022, 9, 1) + relativedelta(months=6, days=15)
            assert end == expected_end

            # Test per-strategy cash
            assert get_initial_cash("ai") == 1000000.0
            assert get_initial_cash("quant") == 1000000.0
            assert get_initial_cash("spy") == 1000000.0


class TestGetReportSettings:
    """Tests for the consolidated report settings loader."""

    def test_report_settings_defaults(self):
        """When no report section is configured, defaults are returned."""

        with patch("stock_analysis.shared.config.load_cfg", return_value={}):
            settings = get_report_settings()

        assert settings == ReportSettings()

    def test_report_settings_parsing_and_validation(self, caplog):
        """Values are coerced and invalid options fall back to defaults."""

        config_data = {
            "report": {
                "report_mode": "comparison_only",
                "with_underwater": "false",
                "index_to_100": "0",
                "use_log_scale": "yes",
                "show_rolling": "True",
                "show_heatmap": "FALSE",
                "rolling_window": "126",
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=config_data):
            settings = get_report_settings()

        assert settings.report_mode == "comparison_only"
        assert settings.with_underwater is False
        assert settings.index_to_100 is False
        assert settings.use_log_scale is True
        assert settings.show_rolling is True
        assert settings.show_heatmap is False
        assert settings.rolling_window == 126

        bad_config = {
            "report": {
                "report_mode": "totally_invalid",
                "rolling_window": 0,
            }
        }

        with patch("stock_analysis.shared.config.load_cfg", return_value=bad_config):
            with caplog.at_level("WARNING"):
                settings = get_report_settings()

        assert settings.report_mode == ReportSettings().report_mode
        assert settings.rolling_window == ReportSettings().rolling_window
        assert "Invalid report_mode" in caplog.text
        assert "Invalid rolling_window" in caplog.text
