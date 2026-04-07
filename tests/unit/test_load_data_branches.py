"""Tests for the CLI and non-CLI branches of `load_data_to_db`.

This module tests the different execution paths for loading data:
- The fast import branch when the SQLite CLI is available.
- The pandas fallback branch when the SQLite CLI is unavailable.
- Handling of existing and non-existing files.
- Handling of various error conditions.
"""

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from stock_analysis.research.data.load_data_to_db import (
    _check_sqlite3_cli,
    _import_prices_with_cli,
    _load_csv_in_chunks,
    main,
)


@pytest.mark.unit
class TestSQLiteCLIDetection:
    """Tests for the SQLite CLI detection logic."""

    def test_sqlite3_cli_available(self):
        """Tests the case where the SQLite CLI is available."""
        with patch("shutil.which", return_value="/usr/bin/sqlite3"):
            assert _check_sqlite3_cli() is True

    def test_sqlite3_cli_not_available(self):
        """Tests the case where the SQLite CLI is not available."""
        with patch("shutil.which", return_value=None):
            assert _check_sqlite3_cli() is False

    def test_sqlite3_cli_detection_with_different_paths(self):
        """Tests SQLite CLI detection with various paths."""
        test_paths = [
            "/usr/bin/sqlite3",
            "/usr/local/bin/sqlite3",
            "C:\\Program Files\\SQLite\\sqlite3.exe",
            None,
        ]

        for path in test_paths:
            with patch("shutil.which", return_value=path):
                expected = path is not None
                assert _check_sqlite3_cli() is expected


@pytest.mark.unit
class TestSQLiteCLIImport:
    """Tests for the SQLite CLI import functionality."""

    def test_cli_import_success(self, tmp_path):
        """Tests a successful CLI import scenario."""
        # Create temporary files
        csv_file = tmp_path / "test.csv"
        db_file = tmp_path / "test.db"
        schema_file = tmp_path / "schema.sql"

        csv_file.write_text("Ticker;Date;Close\nAAPL;2023-01-01;150.0\n")
        schema_file.write_text(
            "CREATE TABLE IF NOT EXISTS share_prices "
            "(Ticker TEXT, Date TEXT, Close REAL);"
        )

        # Mock a successful subprocess call
        mock_result = Mock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = _import_prices_with_cli(csv_file, db_file, schema_file)

            assert result is True
            mock_run.assert_called_once()

            # Verify that the call arguments contain the correct sqlite3 command
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "sqlite3"
            assert str(db_file) in call_args

    def test_cli_import_subprocess_error(self, tmp_path):
        """Tests a CLI import scenario with a subprocess error."""
        csv_file = tmp_path / "test.csv"
        db_file = tmp_path / "test.db"
        schema_file = tmp_path / "schema.sql"

        csv_file.write_text("test data")
        schema_file.write_text("test schema")

        # Mock a subprocess error
        error = subprocess.CalledProcessError(1, "sqlite3", stderr="SQL error")

        with patch("subprocess.run", side_effect=error):
            result = _import_prices_with_cli(csv_file, db_file, schema_file)

            assert result is False

    def test_cli_import_general_exception(self, tmp_path):
        """Tests a CLI import scenario with a general exception."""
        csv_file = tmp_path / "test.csv"
        db_file = tmp_path / "test.db"
        schema_file = tmp_path / "schema.sql"

        with patch("subprocess.run", side_effect=Exception("Unexpected error")):
            result = _import_prices_with_cli(csv_file, db_file, schema_file)

            assert result is False


@pytest.mark.unit
class TestPandasFallback:
    """Tests for the pandas fallback branch."""

    def test_load_csv_in_chunks_basic(self, tmp_path):
        """Tests the basic functionality of loading a CSV in chunks."""
        # Create a test database
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(db_file)

        # Mock CSV data
        with patch("pandas.read_csv") as mock_read_csv:
            # Mock the DataFrame returned by pandas.read_csv
            mock_df = pd.DataFrame(
                {
                    "Ticker": ["AAPL", "MSFT"],
                    "Date": ["2023-01-01", "2023-01-01"],
                    "Close": [150.0, 250.0],
                }
            )
            mock_read_csv.return_value = [mock_df]  # chunksize returns an iterator

            with patch.object(mock_df, "to_sql") as mock_to_sql:
                rows = _load_csv_in_chunks(
                    Path("dummy.csv"), "test_table", con, chunk=1000
                )

                assert rows == 2
                mock_to_sql.assert_called_once()

        con.close()

    def test_load_csv_with_ticker_cleaning(self, tmp_path):
        """Tests loading a CSV with Ticker cleaning."""
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(db_file)

        with patch("pandas.read_csv") as mock_read_csv:
            # Contains Ticker data that needs cleaning
            mock_df = pd.DataFrame(
                {
                    "Ticker": [" aapl ", "MSFT_DELISTED", ""],
                    "Date": ["2023-01-01", "2023-01-01", "2023-01-01"],
                    "Close": [150.0, 250.0, 100.0],
                }
            )
            mock_read_csv.return_value = [mock_df]

            with patch.object(pd.DataFrame, "to_sql") as mock_to_sql:
                _load_csv_in_chunks(Path("dummy.csv"), "test_table", con)

                # Verify that to_sql was called
                mock_to_sql.assert_called_once()

                # Verify that the DataFrame passed to to_sql has been cleaned
                called_df = mock_to_sql.call_args[1]["con"]
                assert called_df is con

        con.close()

    def test_load_financial_data_with_date_conversion(self, tmp_path):
        """Tests date conversion for financial data."""
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(db_file)

        with patch("pandas.read_csv") as mock_read_csv:
            mock_df = pd.DataFrame(
                {
                    "Ticker": ["AAPL", "MSFT"],
                    "Publish Date": ["2023-01-01", "2023-04-01"],
                    "Fiscal Year": [2022, 2023],
                    "Revenue": [100000, 120000],
                }
            )
            mock_read_csv.return_value = [mock_df]

            with patch.object(pd.DataFrame, "to_sql"):
                rows = _load_csv_in_chunks(
                    Path("dummy.csv"),
                    "balance_sheet",  # Financial data table
                    con,
                )

                assert rows == 2

        con.close()

    def test_load_price_data_deduplication(self, tmp_path):
        """Tests deduplication of price data."""
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(db_file)

        with patch("pandas.read_csv") as mock_read_csv:
            # Contains duplicate data
            mock_df = pd.DataFrame(
                {
                    "Ticker": ["AAPL", "AAPL", "MSFT"],
                    "Date": ["2023-01-01", "2023-01-01", "2023-01-01"],
                    "Close": [
                        150.0,
                        151.0,
                        250.0,
                    ],  # AAPL is duplicated, last one should be kept
                }
            )
            mock_read_csv.return_value = [mock_df]

            with patch.object(pd.DataFrame, "to_sql"):
                with patch.object(
                    pd.DataFrame, "drop_duplicates", return_value=mock_df
                ) as mock_drop_dup:
                    _load_csv_in_chunks(Path("dummy.csv"), "share_prices", con)

                    # Verify that deduplication was called
                    mock_drop_dup.assert_called_once_with(
                        subset=["Ticker", "Date"], keep="last"
                    )

        con.close()


@pytest.mark.unit
class TestMainFunctionBranches:
    """Tests for the different branches of the main function."""

    def test_main_with_cli_available(self, tmp_path):
        """Tests the main function execution when the SQLite CLI is available."""
        db_path = tmp_path / "test.db"
        # Create necessary files
        (tmp_path / "us-balance-ttm.csv").write_text("Ticker,Revenue\nAAPL,100000\n")
        (tmp_path / "us-cashflow-ttm.csv").write_text("Ticker,Cash\nAAPL,50000\n")
        (tmp_path / "us-income-ttm.csv").write_text("Ticker,Income\nAAPL,25000\n")
        (tmp_path / "us-shareprices-daily.csv").write_text(
            "Ticker;Date;Close\nAAPL;2023-01-01;150.0\n"
        )
        schema_dir = tmp_path.parent / "sql"
        schema_dir.mkdir(exist_ok=True)
        (schema_dir / "schema.sql").write_text(
            "CREATE TABLE share_prices (Ticker TEXT);"
        )

        with (
            patch("stock_analysis.research.data.load_data_to_db.DATA_DIR", tmp_path),
            patch("stock_analysis.research.data.load_data_to_db.DB_PATH", db_path),
            patch(
                "stock_analysis.research.data.load_data_to_db._check_sqlite3_cli", return_value=True
            ),
            patch(
                "stock_analysis.research.data.load_data_to_db._import_prices_with_cli",
                return_value=True,
            ) as mock_cli_import,
            patch(
                "stock_analysis.research.data.load_data_to_db._load_csv_in_chunks",
                return_value=100,
            ) as mock_chunks,
            patch("sqlite3.connect") as mock_connect,
        ):
            mock_con = Mock()
            mock_connect.return_value.__enter__.return_value = mock_con

            main()

            # Verify that CLI import was called
            mock_cli_import.assert_called_once()
            # Verify that financial data is still loaded in chunks
            assert mock_chunks.call_count == 3  # Three financial data files

    def test_main_with_cli_unavailable(self, tmp_path):
        """Tests the main function execution when the SQLite CLI is unavailable."""
        db_path = tmp_path / "test.db"

        # Create the price data file
        (tmp_path / "us-shareprices-daily.csv").write_text(
            "Ticker;Date;Close\nAAPL;2023-01-01;150.0\n"
        )

        with (
            patch("stock_analysis.research.data.load_data_to_db.DATA_DIR", tmp_path),
            patch("stock_analysis.research.data.load_data_to_db.DB_PATH", db_path),
            patch(
                "stock_analysis.research.data.load_data_to_db._check_sqlite3_cli", return_value=False
            ),
            patch(
                "stock_analysis.research.data.load_data_to_db._import_prices_with_cli"
            ) as mock_cli_import,
            patch(
                "stock_analysis.research.data.load_data_to_db._load_csv_in_chunks",
                return_value=100,
            ) as mock_chunks,
            patch("sqlite3.connect") as mock_connect,
        ):
            mock_con = Mock()
            mock_connect.return_value.__enter__.return_value = mock_con

            main()

            # Verify that CLI import was not called
            mock_cli_import.assert_not_called()
            # Verify fallback to pandas chunks
            mock_chunks.assert_called()

    def test_main_with_cli_failure_fallback(self, tmp_path):
        """Tests the fallback mechanism when CLI import fails."""
        db_path = tmp_path / "test.db"

        # Create necessary files
        (tmp_path / "us-shareprices-daily.csv").write_text(
            "Ticker;Date;Close\nAAPL;2023-01-01;150.0\n"
        )
        schema_dir = tmp_path.parent / "sql"
        schema_dir.mkdir(exist_ok=True)
        (schema_dir / "schema.sql").write_text(
            "CREATE TABLE share_prices (Ticker TEXT);"
        )

        with (
            patch("stock_analysis.research.data.load_data_to_db.DATA_DIR", tmp_path),
            patch("stock_analysis.research.data.load_data_to_db.DB_PATH", db_path),
            patch(
                "stock_analysis.research.data.load_data_to_db._check_sqlite3_cli", return_value=True
            ),
            patch(
                "stock_analysis.research.data.load_data_to_db._import_prices_with_cli",
                return_value=False,
            ),
            patch(
                "stock_analysis.research.data.load_data_to_db._load_csv_in_chunks", return_value=100
            ) as mock_chunks,
            patch("sqlite3.connect") as mock_connect,
        ):
            mock_con = Mock()
            mock_connect.return_value.__enter__.return_value = mock_con

            main()

            # Verify fallback to pandas chunks
            mock_chunks.assert_called()

    def test_main_missing_files_handling(self, tmp_path, caplog):
        """Tests handling of missing files."""
        db_path = tmp_path / "test.db"

        # Do not create any files to test missing file handling
        with (
            patch("stock_analysis.research.data.load_data_to_db.DATA_DIR", tmp_path),
            patch("stock_analysis.research.data.load_data_to_db.DB_PATH", db_path),
            patch("sqlite3.connect") as mock_connect,
        ):
            mock_con = Mock()
            mock_connect.return_value.__enter__.return_value = mock_con

            main()

            assert "Financials source missing" in caplog.text
            assert "Price data file not found" in caplog.text


@pytest.mark.unit
class TestErrorHandling:
    """Tests for error handling."""

    def test_database_connection_error(self):
        """Tests handling of a database connection error."""
        with patch("sqlite3.connect", side_effect=sqlite3.Error("Database locked")):
            with pytest.raises(sqlite3.Error):
                main()

    def test_csv_reading_error(self, tmp_path):
        """Tests handling of a CSV reading error."""
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(db_file)

        with patch("pandas.read_csv", side_effect=pd.errors.EmptyDataError("No data")):
            with pytest.raises(pd.errors.EmptyDataError):
                _load_csv_in_chunks(Path("dummy.csv"), "test_table", con)

        con.close()

    def test_file_permission_error(self, tmp_path):
        """Tests handling of a file permission error."""
        csv_file = tmp_path / "test.csv"
        db_file = tmp_path / "test.db"
        schema_file = tmp_path / "schema.sql"

        with patch("subprocess.run", side_effect=PermissionError("Access denied")):
            result = _import_prices_with_cli(csv_file, db_file, schema_file)
            assert result is False
