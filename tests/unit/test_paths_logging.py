"""Tests for the path management and logging utility modules.

This file tests the functionality in utils.paths and utils.logging, including:
- Project root, output directory creation, and database path constants from utils.paths.
- A smoke test to ensure the setup_logging logger correctly writes to
  outputs/ai_backtest.log (using a temporary directory).
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from stock_analysis.shared.logging import StrategyLogger, setup_logging
from stock_analysis.shared.utils.paths import (
    AI_PORTFOLIO_FILE,
    DATA_DIR,
    DB_PATH,
    DEFAULT_INITIAL_CASH,
    OUTPUTS_DIR,
    PROJECT_ROOT,
    QUANT_PORTFOLIO_FILE,
    SPY_INITIAL_CASH,
    get_project_root,
)


class TestPaths:
    """Tests for path management functionality."""

    def test_get_project_root(self):
        """Tests the get_project_root function."""
        root = get_project_root()

        # Verify that the return value is a Path object
        assert isinstance(root, Path)

        # Verify that the path exists
        assert root.exists()

        # Verify that it is an absolute path
        assert root.is_absolute()

    def test_get_project_root_in_interactive_environment(self, monkeypatch):
        """Tests getting the project root in an interactive environment."""
        import stock_analysis.shared.utils.paths as paths

        # Simulate the absence of __file__ and ensure cwd() is used
        monkeypatch.delattr(paths, "__file__", raising=False)
        expected_dir = Path("/mock/current/dir")
        monkeypatch.setattr(Path, "cwd", lambda: expected_dir)

        root = paths.get_project_root()
        assert root == expected_dir

    def test_project_root_constant(self):
        """Tests the PROJECT_ROOT constant."""
        assert isinstance(PROJECT_ROOT, Path)
        assert PROJECT_ROOT.is_absolute()

    def test_data_dir_path(self):
        """Tests the DATA_DIR path."""
        assert isinstance(DATA_DIR, Path)
        assert DATA_DIR == PROJECT_ROOT / "data"
        assert DATA_DIR.is_absolute()

    def test_outputs_dir_creation(self):
        """Tests the automatic creation of OUTPUTS_DIR."""
        assert isinstance(OUTPUTS_DIR, Path)
        assert OUTPUTS_DIR == PROJECT_ROOT / "outputs"
        assert OUTPUTS_DIR.is_absolute()

        # Verify the directory exists (it should be created automatically)
        assert OUTPUTS_DIR.exists()
        assert OUTPUTS_DIR.is_dir()

    def test_db_path_constant(self):
        """Tests the database path constant."""
        assert isinstance(DB_PATH, Path)
        assert DB_PATH == DATA_DIR / "financial_data.db"
        assert DB_PATH.suffix == ".db"

    def test_portfolio_file_paths(self):
        """Tests the portfolio file paths."""
        # AI portfolio file
        assert isinstance(AI_PORTFOLIO_FILE, Path)
        assert (
            AI_PORTFOLIO_FILE
            == OUTPUTS_DIR / "point_in_time_ai_stock_picks_all_sheets.xlsx"
        )
        assert AI_PORTFOLIO_FILE.suffix == ".xlsx"

        # Quantitative portfolio file
        assert isinstance(QUANT_PORTFOLIO_FILE, Path)
        assert (
            QUANT_PORTFOLIO_FILE
            == OUTPUTS_DIR / "point_in_time_backtest_quarterly_sp500_historical.xlsx"
        )
        assert QUANT_PORTFOLIO_FILE.suffix == ".xlsx"

    def test_initial_cash_constants(self):
        """Tests the initial cash constants."""
        assert isinstance(DEFAULT_INITIAL_CASH, float)
        assert DEFAULT_INITIAL_CASH == 1_000_000.0

        assert isinstance(SPY_INITIAL_CASH, float)
        assert SPY_INITIAL_CASH == 100_000.0

        # Verify reasonableness
        assert DEFAULT_INITIAL_CASH > 0
        assert SPY_INITIAL_CASH > 0

    def test_path_relationships(self):
        """Tests the relationships between paths."""
        # Verify all paths are based on PROJECT_ROOT
        assert DATA_DIR.is_relative_to(PROJECT_ROOT)
        assert OUTPUTS_DIR.is_relative_to(PROJECT_ROOT)

        # Verify file paths are based on the correct directories
        assert DB_PATH.is_relative_to(DATA_DIR)
        assert AI_PORTFOLIO_FILE.is_relative_to(OUTPUTS_DIR)
        assert QUANT_PORTFOLIO_FILE.is_relative_to(OUTPUTS_DIR)


class TestSetupLogging:
    """Tests for the logging setup functionality."""

    def test_basic_logger_setup(self):
        """Tests the basic logger setup."""
        logger = setup_logging("test_logger")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_logger_with_file_output(self, tmp_path):
        """Tests a logger with file output."""
        # Temporarily modify OUTPUTS_DIR
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            logger = setup_logging("file_logger", log_file="test.log")

            # Test logging a record
            logger.info("Test message")

            # Verify the log file was created
            log_file = tmp_path / "test.log"
            assert log_file.exists()

            # Verify the log content
            log_content = log_file.read_text(encoding="utf-8")
            assert "Test message" in log_content
            assert "file_logger" in log_content

    def test_logger_without_console(self):
        """Tests a logger without console output."""
        logger = setup_logging("no_console_logger", use_console=False)

        # There should be no StreamHandler
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 0

    def test_logger_custom_level(self):
        """Tests a custom log level."""
        logger = setup_logging("debug_logger", level=logging.DEBUG)

        assert logger.level == logging.DEBUG

        # Verify that handlers are also set to the correct level
        for handler in logger.handlers:
            assert handler.level == logging.DEBUG

    def test_logger_duplicate_setup_prevention(self):
        """Tests the prevention of duplicate logger setup."""
        # First setup
        logger1 = setup_logging("duplicate_test")
        initial_handler_count = len(logger1.handlers)

        # Second setup of a logger with the same name
        logger2 = setup_logging("duplicate_test")

        # It should return the same logger instance,
        # and the handler count should not change
        assert logger1 is logger2
        assert len(logger2.handlers) == initial_handler_count

    def test_logger_formatter(self, tmp_path):
        """Tests the log formatter."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            logger = setup_logging("format_test", log_file="format_test.log")
            logger.info("Format test message")

            log_file = tmp_path / "format_test.log"
            log_content = log_file.read_text(encoding="utf-8")

            # Verify the format contains expected elements
            assert "format_test" in log_content  # logger name
            assert "INFO" in log_content  # log level
            assert "Format test message" in log_content  # message
            # Verify the timestamp format (YYYY-MM-DD HH:MM:SS)
            import re

            timestamp_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
            assert re.search(timestamp_pattern, log_content)

    def test_ai_backtest_log_smoke_test(self, tmp_path):
        """Smoke test for the AI backtest log."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            # Simulate the AI backtest logger setup
            logger = setup_logging("ai_backtest", log_file="ai_backtest.log")

            # Simulate some typical AI backtest log messages
            logger.info("Starting AI backtest...")
            logger.info("Loading portfolios from Excel file")
            logger.info("Processing quarter 2022-Q1")
            logger.warning("Missing price data for TICKER_XYZ")
            logger.info("Backtest completed successfully")

            # Verify the log file exists and contains the expected content
            log_file = tmp_path / "ai_backtest.log"
            assert log_file.exists()

            log_content = log_file.read_text(encoding="utf-8")
            assert "Starting AI backtest" in log_content
            assert "Loading portfolios" in log_content
            assert "Processing quarter" in log_content
            assert "Missing price data" in log_content
            assert "Backtest completed" in log_content


class TestStrategyLogger:
    """Tests for the StrategyLogger."""

    def test_strategy_logger_with_logging(self, tmp_path):
        """Tests StrategyLogger when using the logging module."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            strategy_logger = StrategyLogger(
                use_logging=True, logger_name="test_strategy"
            )

            assert strategy_logger.use_logging
            assert strategy_logger.logger is not None
            assert isinstance(strategy_logger.logger, logging.Logger)

    def test_strategy_logger_with_print(self):
        """Tests StrategyLogger when using the print function."""
        strategy_logger = StrategyLogger(use_logging=False)

        assert not strategy_logger.use_logging
        assert strategy_logger.logger is None

    def test_strategy_logger_log_method_with_datetime(self, capsys):
        """Tests the log method with a datetime object."""
        import datetime

        strategy_logger = StrategyLogger(use_logging=False)
        test_date = datetime.date(2022, 1, 15)

        strategy_logger.log("Test message", dt=test_date)

        captured = capsys.readouterr()
        assert "2022-01-15" in captured.out
        assert "Test message" in captured.out

    def test_strategy_logger_log_method_without_datetime(self, capsys):
        """Tests the log method without a datetime object."""
        strategy_logger = StrategyLogger(use_logging=False)

        strategy_logger.log("Simple test message")

        captured = capsys.readouterr()
        assert "Simple test message" in captured.out

    def test_strategy_logger_info_method(self, capsys):
        """Tests the info method."""
        strategy_logger = StrategyLogger(use_logging=False)

        strategy_logger.info("Info message")

        captured = capsys.readouterr()
        assert "Info message" in captured.out

    def test_strategy_logger_warning_method(self, capsys):
        """Tests the warning method."""
        strategy_logger = StrategyLogger(use_logging=False)

        strategy_logger.warning("Warning message")

        captured = capsys.readouterr()
        assert "WARNING: Warning message" in captured.out

    def test_strategy_logger_error_method(self, capsys):
        """Tests the error method."""
        strategy_logger = StrategyLogger(use_logging=False)

        strategy_logger.error("Error message")

        captured = capsys.readouterr()
        assert "ERROR: Error message" in captured.err

    def test_strategy_logger_with_real_logging(self, tmp_path):
        """Tests StrategyLogger with a real logging backend."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            # Create a StrategyLogger that uses the logging module
            strategy_logger = StrategyLogger(
                use_logging=True, logger_name="real_logging_test"
            )

            # Set up file logging
            strategy_logger.logger = setup_logging(
                "real_logging_test", log_file="strategy_test.log"
            )

            # Test various logging methods
            strategy_logger.info("Strategy info message")
            strategy_logger.warning("Strategy warning message")
            strategy_logger.error("Strategy error message")

            # Verify the log file
            log_file = tmp_path / "strategy_test.log"
            assert log_file.exists()

            log_content = log_file.read_text(encoding="utf-8")
            assert "Strategy info message" in log_content
            assert "Strategy warning message" in log_content
            assert "Strategy error message" in log_content


class TestLoggingIntegration:
    """Integration tests for logging functionality."""

    def test_multiple_loggers_isolation(self, tmp_path):
        """Tests the isolation of multiple loggers."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            # Create two different loggers
            logger1 = setup_logging("logger1", log_file="log1.log")
            logger2 = setup_logging("logger2", log_file="log2.log")

            # Log different messages
            logger1.info("Message from logger1")
            logger2.info("Message from logger2")

            # Verify that the log files are separate
            log1_content = (tmp_path / "log1.log").read_text(encoding="utf-8")
            log2_content = (tmp_path / "log2.log").read_text(encoding="utf-8")

            assert "Message from logger1" in log1_content
            assert "Message from logger1" not in log2_content

            assert "Message from logger2" in log2_content
            assert "Message from logger2" not in log1_content

    def test_strategy_logger_compatibility(self, tmp_path):
        """Tests the compatibility between StrategyLogger and a standard logger."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            # Create a standard logger
            standard_logger = setup_logging("standard", log_file="standard.log")

            # Create a StrategyLogger
            strategy_logger = StrategyLogger(
                use_logging=True, logger_name="strategy_compat"
            )
            strategy_logger.logger = setup_logging(
                "strategy_compat", log_file="strategy.log"
            )

            # Log messages with both
            standard_logger.info("Standard logger message")
            strategy_logger.info("Strategy logger message")

            # Verify that both log files work correctly
            standard_content = (tmp_path / "standard.log").read_text(encoding="utf-8")
            strategy_content = (tmp_path / "strategy.log").read_text(encoding="utf-8")

            assert "Standard logger message" in standard_content
            assert "Strategy logger message" in strategy_content

    @pytest.mark.slow
    def test_logging_performance_smoke_test(self, tmp_path, monkeypatch):
        """Smoke test for logging performance."""
        import time

        # Use a controllable clock to avoid real-time delays
        fake_time = {"t": 0.0}

        def fake_time_func():
            fake_time["t"] += 0.001
            return fake_time["t"]

        monkeypatch.setattr(time, "time", fake_time_func)
        monkeypatch.setattr(time, "sleep", lambda _x: None)

        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            logger = setup_logging("performance_test", filename="performance.log")

            start_time = time.time()

            for i in range(10):
                logger.info(f"Performance test message {i}")

            elapsed_time = time.time() - start_time

            # Verify performance is reasonable (10 messages should complete quickly)
            assert elapsed_time < 5.0  # Should complete within 5 seconds

            log_content = (tmp_path / "performance.log").read_text(encoding="utf-8")
            assert "Performance test message 0" in log_content
            assert "Performance test message 9" in log_content

    def test_unicode_logging_support(self, tmp_path):
        """Tests support for logging Unicode characters."""
        with patch("stock_analysis.shared.logging.OUTPUTS_DIR", tmp_path):
            logger = setup_logging("unicode_test", log_file="unicode.log")

            # Log messages containing Unicode characters
            unicode_messages = [
                "测试中文日志消息",  # Test Chinese log message
                "Тест русского сообщения",  # Test Russian message
                "Test émojis: 📈📊💰",
                "Special chars: ñáéíóú",
            ]

            for msg in unicode_messages:
                logger.info(msg)

            # Verify that Unicode characters are saved correctly
            log_content = (tmp_path / "unicode.log").read_text(encoding="utf-8")

            for msg in unicode_messages:
                assert msg in log_content
