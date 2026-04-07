"""Tests for the database reading and data source preparation module.

This file tests database-related functionalities, including:
- load_spy_data and load_price_feeds: Raise errors if the database doesn't exist or
  is empty, fill null Dividend values, and ensure the returned index is 'Date'.
- load_data_to_db: Confirm successful table creation, data insertion, and composite
  index creation.
"""

import datetime
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from stock_analysis.research.backtest.prep import load_price_feeds, load_spy_data
from stock_analysis.research.data.load_data_to_db import main as load_data_main

pytestmark = pytest.mark.integration


class TestLoadSpyData:
    """Tests for the load_spy_data function."""

    def create_test_database(self, db_path: Path, include_data: bool = True) -> None:
        """Creates a test database.

        Args:
            db_path: The path to the database file.
            include_data: Whether to include test data.
        """
        con = sqlite3.connect(db_path)

        # Create table structure
        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT,
                Ticker TEXT,
                Open REAL,
                High REAL,
                Low REAL,
                Close REAL,
                Volume INTEGER,
                Dividend REAL
            )
        """)

        if include_data:
            # Insert test data
            test_data = [
                ("2022-01-03", "SPY", 477.71, 479.98, 477.51, 478.96, 76196200, 0.0),
                ("2022-01-04", "SPY", 478.31, 478.65, 474.73, 475.01, 99310400, 0.0),
                ("2022-01-05", "SPY", 474.17, 474.17, 467.04, 467.94, 134235000, 0.0),
                ("2022-01-06", "SPY", 467.71, 470.58, 462.66, 463.04, 111598600, 0.0),
                ("2022-01-07", "SPY", 464.26, 466.47, 461.72, 462.32, 86185500, 0.0),
                # Include some data with dividends
                ("2022-03-18", "SPY", 440.00, 445.00, 439.00, 444.00, 50000000, 1.57),
                ("2022-06-17", "SPY", 370.00, 375.00, 368.00, 372.00, 60000000, 1.61),
                # Include some data with NULL Dividends
                ("2022-01-10", "SPY", 465.00, 467.00, 463.00, 465.50, 75000000, None),
                ("2022-01-11", "SPY", 466.00, 468.00, 464.00, 467.20, 80000000, None),
            ]

            con.executemany(
                "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
            )

        con.commit()
        con.close()

    def test_database_not_found(self, tmp_path):
        """Test error handling when the database file does not exist."""
        non_existent_db = tmp_path / "non_existent.db"
        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        with pytest.raises(FileNotFoundError, match="Database file not found"):
            load_spy_data(non_existent_db, start_date, end_date)

    def test_no_data_found(self, tmp_path):
        """Test error handling when the database exists but contains no data."""
        db_path = tmp_path / "empty.db"
        self.create_test_database(db_path, include_data=False)

        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        with pytest.raises(ValueError, match="No SPY data found in database"):
            load_spy_data(db_path, start_date, end_date)

    def test_successful_data_loading(self, tmp_path):
        """Test successful data loading."""
        db_path = tmp_path / "test.db"
        self.create_test_database(db_path, include_data=True)

        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        result = load_spy_data(db_path, start_date, end_date)

        # Verify the structure of the returned DataFrame
        assert isinstance(result, pd.DataFrame)
        assert isinstance(result.index, pd.DatetimeIndex)

        expected_columns = ["Open", "High", "Low", "Close", "Volume", "Dividend"]
        assert list(result.columns) == expected_columns

        # Verify the data content
        assert len(result) == 9  # Should be 9 rows of data
        assert result.index.name == "Date"

        # Verify the date range
        assert result.index.min().date() >= start_date.date()
        assert result.index.max().date() <= end_date.date()

    def test_dividend_null_filling(self, tmp_path):
        """Test the filling of null Dividend values."""
        db_path = tmp_path / "test.db"
        self.create_test_database(db_path, include_data=True)

        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        result = load_spy_data(db_path, start_date, end_date)

        # Verify the Dividend column has no null values
        assert not result["Dividend"].isna().any()

        # Verify that NULL values were filled with 0.0
        dividend_values = result["Dividend"].values
        assert 0.0 in dividend_values  # The original NULLs should now be 0.0
        assert 1.57 in dividend_values  # Existing values should remain unchanged
        assert 1.61 in dividend_values

    def test_date_filtering(self, tmp_path):
        """Test the date range filtering functionality."""
        db_path = tmp_path / "test.db"
        self.create_test_database(db_path, include_data=True)

        # Test with a smaller date range
        start_date = datetime.datetime(2022, 1, 3)
        end_date = datetime.datetime(2022, 1, 7)

        result = load_spy_data(db_path, start_date, end_date)

        # Should only contain data within the specified date range
        assert len(result) == 5
        assert result.index.min().date() == datetime.date(2022, 1, 3)
        assert result.index.max().date() == datetime.date(2022, 1, 7)

    def test_custom_ticker(self, tmp_path):
        """Test loading data for a custom ticker."""
        db_path = tmp_path / "test.db"
        con = sqlite3.connect(db_path)

        # Create data for multiple tickers
        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)

        test_data = [
            ("2022-01-03", "AAPL", 177.83, 182.88, 177.71, 182.01, 104487900, 0.0),
            ("2022-01-04", "AAPL", 182.63, 182.94, 179.12, 179.70, 99310400, 0.0),
            ("2022-01-03", "SPY", 477.71, 479.98, 477.51, 478.96, 76196200, 0.0),
            ("2022-01-04", "SPY", 478.31, 478.65, 474.73, 475.01, 99310400, 0.0),
        ]

        con.executemany(
            "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
        )
        con.commit()
        con.close()

        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        # Test loading AAPL data
        result = load_spy_data(db_path, start_date, end_date, ticker="AAPL")

        assert len(result) == 2
        assert result["Close"].iloc[0] == 182.01
        assert result["Close"].iloc[1] == 179.70


class TestLoadPriceFeeds:
    """Tests for the load_price_feeds function."""

    def create_multi_ticker_database(self, db_path: Path) -> None:
        """Creates a test database with multiple stock tickers."""
        con = sqlite3.connect(db_path)

        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)

        # Create test data for multiple tickers
        test_data = [
            # AAPL data
            ("2022-01-03", "AAPL", 177.83, 182.88, 177.71, 182.01, 104487900, 0.0),
            ("2022-01-04", "AAPL", 182.63, 182.94, 179.12, 179.70, 99310400, 0.0),
            ("2022-01-05", "AAPL", 179.61, 180.17, 174.64, 174.92, 94537600, 0.0),
            # MSFT data
            ("2022-01-03", "MSFT", 331.62, 336.06, 330.59, 334.75, 23454000, 0.0),
            ("2022-01-04", "MSFT", 334.15, 334.91, 329.93, 331.30, 37811700, 0.0),
            ("2022-01-05", "MSFT", 330.70, 331.47, 325.83, 325.87, 49047300, 0.0),
            # GOOGL data (partially missing)
            ("2022-01-03", "GOOGL", 2752.88, 2810.00, 2752.88, 2804.18, 1469600, 0.0),
            ("2022-01-05", "GOOGL", 2800.00, 2825.00, 2750.00, 2751.25, 1500000, 0.0),
            # Include dividend data
            ("2022-01-06", "AAPL", 175.00, 176.00, 174.00, 175.50, 80000000, None),
            ("2022-01-06", "MSFT", 326.00, 328.00, 325.00, 327.20, 45000000, 0.68),
        ]

        con.executemany(
            "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
        )
        con.commit()
        con.close()

    def test_database_not_found(self, tmp_path):
        """Test error handling when the database file does not exist."""
        non_existent_db = tmp_path / "non_existent.db"
        tickers = {"AAPL", "MSFT"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        with pytest.raises(FileNotFoundError, match="Database file not found"):
            load_price_feeds(non_existent_db, tickers, start_date, end_date)

    def test_no_trading_days_found(self, tmp_path):
        """Test error handling when no trading day data is found."""
        db_path = tmp_path / "empty.db"
        con = sqlite3.connect(db_path)
        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)
        con.commit()
        con.close()

        tickers = {"AAPL", "MSFT"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        with pytest.raises(ValueError, match="No trading days found in the database"):
            load_price_feeds(db_path, tickers, start_date, end_date)

    def test_successful_data_loading(self, tmp_path):
        """Test the successful loading of data feeds for multiple stocks."""
        db_path = tmp_path / "test.db"
        self.create_multi_ticker_database(db_path)

        tickers = {"AAPL", "MSFT", "GOOGL"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        result = load_price_feeds(db_path, tickers, start_date, end_date)

        # Verify the returned dictionary of data feeds
        assert isinstance(result, dict)
        assert len(result) == 3  # Should contain data feeds for 3 stocks

        # Verify each ticker has a corresponding data feed
        for ticker in tickers:
            assert ticker in result
            # Verify the data feed type (checking structure, not backtrader internals)
            assert hasattr(result[ticker], "dataname")

    def test_dividend_filling(self, tmp_path):
        """Test the filling of dividend data."""
        db_path = tmp_path / "test.db"
        self.create_multi_ticker_database(db_path)

        tickers = {"AAPL", "MSFT"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        result = load_price_feeds(db_path, tickers, start_date, end_date)

        # Verify data feeds were created correctly
        assert "AAPL" in result
        assert "MSFT" in result

        # Verify the data feeds contain the expected data
        aapl_data = result["AAPL"].dataname
        msft_data = result["MSFT"].dataname

        # Verify the Dividend column exists and has no NaN values
        assert "Dividend" in aapl_data.columns
        assert "Dividend" in msft_data.columns
        assert not aapl_data["Dividend"].isna().any()
        assert not msft_data["Dividend"].isna().any()

    def test_dividend_not_forward_filled(self, tmp_path):
        """Ensure dividends are not forward filled across the timeline."""
        db_path = tmp_path / "test.db"
        self.create_multi_ticker_database(db_path)

        tickers = {"MSFT"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        result = load_price_feeds(db_path, tickers, start_date, end_date)

        msft_data = result["MSFT"].dataname

        # Dividend should only appear on the actual dividend date
        non_zero_dividends = msft_data[msft_data["Dividend"] > 0]
        assert len(non_zero_dividends) == 1
        assert non_zero_dividends.index[0].date() == datetime.date(2022, 1, 6)

        # All other dates should have zero dividend
        assert (msft_data.loc[msft_data.index.date != datetime.date(2022, 1, 6), "Dividend"] == 0).all()

    def test_data_deduplication(self, tmp_path):
        """Test the data deduplication functionality."""
        db_path = tmp_path / "test.db"
        con = sqlite3.connect(db_path)

        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)

        # Insert duplicate data
        test_data = [
            ("2022-01-03", "AAPL", 177.83, 182.88, 177.71, 182.01, 104487900, 0.0),
            (
                "2022-01-03",
                "AAPL",
                177.83,
                182.88,
                177.71,
                182.01,
                104487900,
                0.0,
            ),  # Duplicate
            (
                "2022-01-03",
                "AAPL",
                178.00,
                183.00,
                178.00,
                182.50,
                105000000,
                0.0,
            ),  # Same date, different data
            ("2022-01-04", "AAPL", 182.63, 182.94, 179.12, 179.70, 99310400, 0.0),
        ]

        con.executemany(
            "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
        )
        con.commit()
        con.close()

        tickers = {"AAPL"}
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        result = load_price_feeds(db_path, tickers, start_date, end_date)

        # Verify the data after deduplication
        aapl_data = result["AAPL"].dataname

        # Should only have 2 rows of data (after deduplication)
        assert len(aapl_data) == 2

        # Verify that the last record was kept (keep='last')
        jan_3_data = aapl_data.loc[aapl_data.index.date == datetime.date(2022, 1, 3)]
        assert len(jan_3_data) == 1
        assert (
            jan_3_data["Close"].iloc[0] == 182.50
        )  # Should be the value from the last record


class TestLoadDataToDb:
    """Tests for database creation and index establishment."""

    def test_database_creation_and_indexes(self, tmp_path):
        """Test database creation and index establishment."""
        # Create temporary data directory and files
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create minimal test CSV files
        balance_sheet_data = (
            "Ticker;Total Assets;Total Liabilities;Publish Date;Fiscal Year\n"
            "AAPL;100000;50000;2022-01-01;2022\n"
            "MSFT;200000;80000;2022-01-01;2022"
        )
        cash_flow_data = (
            "Ticker;Operating Cash Flow;Publish Date;Fiscal Year\n"
            "AAPL;50000;2022-01-01;2022\n"
            "MSFT;60000;2022-01-01;2022"
        )
        income_data = (
            "Ticker;Revenue;Net Income;Publish Date;Fiscal Year\n"
            "AAPL;300000;80000;2022-01-01;2022\n"
            "MSFT;400000;90000;2022-01-01;2022"
        )
        price_data = (
            "Date;Ticker;Open;High;Low;Close;Volume;Dividend\n"
            "2022-01-03;AAPL;177.83;182.88;177.71;182.01;104487900;0.0\n"
            "2022-01-03;MSFT;331.62;336.06;330.59;334.75;23454000;0.0"
        )

        (data_dir / "us-balance-ttm.csv").write_text(balance_sheet_data)
        (data_dir / "us-cashflow-ttm.csv").write_text(cash_flow_data)
        (data_dir / "us-income-ttm.csv").write_text(income_data)
        (data_dir / "us-shareprices-daily.csv").write_text(price_data)

        db_path = data_dir / "financial_data.db"

        # Mock path configurations
        with patch("stock_analysis.research.data.load_data_to_db.PROJECT_ROOT", tmp_path):
            with patch("stock_analysis.research.data.load_data_to_db.DATA_DIR", data_dir):
                with patch("stock_analysis.research.data.load_data_to_db.DB_PATH", db_path):
                    # Execute the database creation
                    load_data_main()

        # Verify the database file was created
        assert db_path.exists()

        # Verify tables and indexes
        con = sqlite3.connect(db_path)

        try:
            # Check if tables exist
            tables_query = "SELECT name FROM sqlite_master WHERE type='table'"
            tables = [row[0] for row in con.execute(tables_query).fetchall()]

            expected_tables = ["balance_sheet", "cash_flow", "income", "share_prices"]
            for table in expected_tables:
                assert table in tables

            # Check if indexes exist
            indexes_query = "SELECT name FROM sqlite_master WHERE type='index'"
            indexes = [row[0] for row in con.execute(indexes_query).fetchall()]

            expected_indexes = [
                "idx_balance_sheet_ticker_date",
                "idx_cash_flow_ticker_date",
                "idx_income_ticker_date",
                "idx_prices_ticker_date",
            ]

            for index in expected_indexes:
                assert index in indexes

            # Verify data was inserted correctly
            balance_count = con.execute(
                "SELECT COUNT(*) FROM balance_sheet"
            ).fetchone()[0]
            assert balance_count == 2

            price_count = con.execute("SELECT COUNT(*) FROM share_prices").fetchone()[0]
            assert price_count == 2

            # Verify ticker cleaning functionality
            tickers = [
                row[0]
                for row in con.execute(
                    "SELECT DISTINCT Ticker FROM share_prices"
                ).fetchall()
            ]
            assert "AAPL" in tickers
            assert "MSFT" in tickers

        finally:
            con.close()

    def test_index_performance_verification(self, tmp_path):
        """Verify that indexes are created and can improve query performance."""
        # Create a test database with more data
        db_path = tmp_path / "test_performance.db"
        con = sqlite3.connect(db_path)

        # Create table
        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)

        # Insert a large amount of test data
        import random

        test_data = []
        tickers = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN"] * 100  # 500 records
        dates = [
            "2022-01-01",
            "2022-01-02",
            "2022-01-03",
            "2022-01-04",
            "2022-01-05",
        ] * 100

        for i in range(500):
            test_data.append(
                (
                    dates[i],
                    tickers[i],
                    random.uniform(100, 200),
                    random.uniform(200, 300),
                    random.uniform(90, 190),
                    random.uniform(110, 210),
                    random.randint(1000000, 10000000),
                    0.0,
                )
            )

        con.executemany(
            "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
        )

        # Create index
        con.execute(
            "CREATE INDEX idx_prices_ticker_date ON share_prices (Ticker, Date)"
        )
        con.commit()

        # Verify index exists
        indexes = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        ]
        assert "idx_prices_ticker_date" in indexes

        # Verify the query plan uses the index
        explain_result = con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM share_prices "
            "WHERE Ticker = 'AAPL' AND Date = '2022-01-01'"
        ).fetchall()

        # The query plan should mention the use of the index
        plan_text = " ".join([str(row) for row in explain_result])
        assert "idx_prices_ticker_date" in plan_text or "INDEX" in plan_text.upper()

        con.close()


class TestDatabaseIntegration:
    """Integration tests for database operations."""

    def test_end_to_end_data_flow(self, tmp_path):
        """End-to-end test: from database creation to data loading."""
        # 1. Create a test database
        db_path = tmp_path / "integration_test.db"
        con = sqlite3.connect(db_path)

        con.execute("""
            CREATE TABLE share_prices (
                Date TEXT, Ticker TEXT, Open REAL, High REAL,
                Low REAL, Close REAL, Volume INTEGER, Dividend REAL
            )
        """)

        # Insert test data
        test_data = [
            ("2022-01-03", "SPY", 477.71, 479.98, 477.51, 478.96, 76196200, 0.0),
            ("2022-01-04", "SPY", 478.31, 478.65, 474.73, 475.01, 99310400, 0.0),
            ("2022-01-03", "AAPL", 177.83, 182.88, 177.71, 182.01, 104487900, 0.0),
            ("2022-01-04", "AAPL", 182.63, 182.94, 179.12, 179.70, 99310400, 0.0),
            ("2022-01-03", "MSFT", 331.62, 336.06, 330.59, 334.75, 23454000, None),
            ("2022-01-04", "MSFT", 334.15, 334.91, 329.93, 331.30, 37811700, 0.68),
        ]

        con.executemany(
            "INSERT INTO share_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", test_data
        )
        con.commit()
        con.close()

        # 2. Test loading SPY data
        start_date = datetime.datetime(2022, 1, 1)
        end_date = datetime.datetime(2022, 12, 31)

        spy_data = load_spy_data(db_path, start_date, end_date)
        assert len(spy_data) == 2
        assert not spy_data["Dividend"].isna().any()

        # 3. Test loading multi-stock price feeds
        tickers = {"AAPL", "MSFT"}
        price_feeds = load_price_feeds(
            db_path, tickers, start_date.date(), end_date.date()
        )

        assert len(price_feeds) == 2
        assert "AAPL" in price_feeds
        assert "MSFT" in price_feeds

        # Verify data integrity
        aapl_data = price_feeds["AAPL"].dataname
        msft_data = price_feeds["MSFT"].dataname

        assert len(aapl_data) == 2
        assert len(msft_data) == 2

        # Verify Dividend filling
        assert not aapl_data["Dividend"].isna().any()
        assert not msft_data["Dividend"].isna().any()
        assert msft_data["Dividend"].iloc[1] == 0.68  # Existing value remains unchanged
