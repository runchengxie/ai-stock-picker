"""Tests for the portfolio loading and cleaning module.

Tests the portfolio loading logic in `backtest.prep`, including:
- `load_portfolios`: Skipping empty sheets, case-insensitive ticker handling, 
  removal of `_DELISTED` suffix, NaN filtering, and parsing sheet names into 
  rebalancing dates.
- `tidy_ticker`: Cleaning of case, whitespace, and suffixes.
"""

import datetime
from pathlib import Path

import pandas as pd
import pytest
import json

from stock_analysis.research.backtest.prep import load_portfolios, tidy_ticker


class TestTidyTicker:
    """Tests the stock ticker cleaning function."""

    def test_uppercase_conversion(self):
        """Tests conversion to uppercase."""
        input_series = pd.Series(["aapl", "MSFT", "googl", "TsLa"])
        result = tidy_ticker(input_series)
        expected = pd.Series(["AAPL", "MSFT", "GOOGL", "TSLA"], dtype="string")
        pd.testing.assert_series_equal(result, expected)

    def test_whitespace_stripping(self):
        """Tests whitespace stripping."""
        input_series = pd.Series(["  AAPL  ", "\tMSFT\n", " GOOGL", "TSLA "])
        result = tidy_ticker(input_series)
        expected = pd.Series(["AAPL", "MSFT", "GOOGL", "TSLA"], dtype="string")
        pd.testing.assert_series_equal(result, expected)

    def test_delisted_suffix_removal(self):
        """Tests the removal of the `_DELISTED` suffix."""
        input_series = pd.Series(["AAPL_DELISTED", "MSFT", "GOOGL_DELISTED", "TSLA"])
        result = tidy_ticker(input_series)
        expected = pd.Series(["AAPL", "MSFT", "GOOGL", "TSLA"], dtype="string")
        pd.testing.assert_series_equal(result, expected)

    def test_empty_string_to_na(self):
        """Tests the conversion of empty strings to NA."""
        input_series = pd.Series(["AAPL", "", "MSFT", "   ", "GOOGL"])
        result = tidy_ticker(input_series)
        expected = pd.Series(["AAPL", pd.NA, "MSFT", pd.NA, "GOOGL"], dtype="string")
        pd.testing.assert_series_equal(result, expected)

    def test_combined_cleaning(self):
        """Tests the combined cleaning logic."""
        input_series = pd.Series(
            ["  aapl_DELISTED  ", "\tMSFT\n", "", "googl_DELISTED", "   ", "TSLA"]
        )
        result = tidy_ticker(input_series)
        expected = pd.Series(
            ["AAPL", "MSFT", pd.NA, "GOOGL", pd.NA, "TSLA"], dtype="string"
        )
        pd.testing.assert_series_equal(result, expected)

    def test_numeric_input_conversion(self):
        """Tests the conversion of numeric input to strings."""
        input_series = pd.Series([123, 456.0, "AAPL"])
        result = tidy_ticker(input_series)
        expected = pd.Series(["123", "456.0", "AAPL"], dtype="string")
        pd.testing.assert_series_equal(result, expected)


class TestLoadPortfolios:
    """Tests the portfolio loading function."""

    def create_test_excel(self, tmp_path: Path, sheets_data: dict) -> Path:
        """Creates a test Excel file.

        Args:
            tmp_path: Path to the temporary directory.
            sheets_data: A dictionary of worksheet data, with the format 
                         {sheet_name: DataFrame}.

        Returns:
            Path: The path to the created Excel file.
        """
        excel_path = tmp_path / "test_portfolios.xlsx"

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets_data.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        return excel_path

    def test_file_not_found(self, tmp_path):
        """Tests exception handling when the file does not exist."""
        non_existent_path = tmp_path / "non_existent.xlsx"

        with pytest.raises(FileNotFoundError, match="Portfolio file not found"):
            load_portfolios(non_existent_path)

    def test_empty_sheets_skipped(self, tmp_path):
        """Tests that empty worksheets are skipped."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(),  # Empty DataFrame
            "2022-04-01": pd.DataFrame({"Ticker": ["AAPL", "MSFT"]}),
            "2022-07-01": pd.DataFrame(),  # Another empty DataFrame
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        # Only non-empty worksheets should be included.
        assert len(portfolios) == 1
        assert datetime.date(2022, 4, 1) in portfolios
        assert datetime.date(2022, 1, 1) not in portfolios
        assert datetime.date(2022, 7, 1) not in portfolios

    def test_ticker_column_missing(self, tmp_path):
        """Tests that worksheets missing a 'Ticker' column are skipped."""
        sheets_data = {
            "2022-01-01": pd.DataFrame({"Symbol": ["AAPL", "MSFT"]}),  # Incorrect column name
            "2022-04-01": pd.DataFrame({"Ticker": ["GOOGL", "TSLA"]}),  # Correct column name
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        # Only worksheets containing a 'Ticker' column should be included.
        assert len(portfolios) == 1
        assert datetime.date(2022, 4, 1) in portfolios
        assert datetime.date(2022, 1, 1) not in portfolios

    def test_ticker_cleaning_and_nan_filtering(self, tmp_path):
        """Tests Ticker cleaning and NaN filtering."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(
                {"Ticker": ["  aapl_DELISTED  ", "MSFT", "", "googl", None, "   "]}
            )
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]

        # Should only keep valid tickers, and they should be cleaned.
        expected_tickers = ["AAPL", "MSFT", "GOOGL"]
        actual_tickers = df["Ticker"].tolist()
        assert actual_tickers == expected_tickers

    def test_sheet_name_to_date_parsing(self, tmp_path):
        """Tests the parsing of worksheet names into dates."""
        sheets_data = {
            "2022-01-01": pd.DataFrame({"Ticker": ["AAPL"]}),
            "2022-04-01": pd.DataFrame({"Ticker": ["MSFT"]}),
            "2022-07-01": pd.DataFrame({"Ticker": ["GOOGL"]}),
            "2022-10-01": pd.DataFrame({"Ticker": ["TSLA"]}),
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        expected_dates = [
            datetime.date(2022, 1, 1),
            datetime.date(2022, 4, 1),
            datetime.date(2022, 7, 1),
            datetime.date(2022, 10, 1),
        ]

        assert len(portfolios) == 4
        for date in expected_dates:
            assert date in portfolios

    def test_ai_selection_column_compatibility(self, tmp_path):
        """Tests column name compatibility for the AI selection version."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(
                {
                    "ticker": ["AAPL", "MSFT"],  # lowercase 'ticker' column
                    "score": [0.85, 0.92],
                }
            )
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)

        # Test AI selection mode
        portfolios = load_portfolios(excel_path, is_ai_selection=True)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]

        # Should automatically rename 'ticker' to 'Ticker'
        assert "Ticker" in df.columns
        assert "ticker" not in df.columns
        assert df["Ticker"].tolist() == ["AAPL", "MSFT"]

    def test_ai_selection_existing_ticker_column(self, tmp_path):
        """Tests the case where a 'Ticker' column already exists in the AI selection version."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(
                {
                    "Ticker": ["AAPL", "MSFT"],  # Already uppercase 'Ticker'
                    "score": [0.85, 0.92],
                }
            )
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path, is_ai_selection=True)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]

        # Should keep the original 'Ticker' column
        assert "Ticker" in df.columns
        assert df["Ticker"].tolist() == ["AAPL", "MSFT"]

    def test_non_ai_selection_mode(self, tmp_path):
        """Tests that non-AI selection mode does not handle column name compatibility."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(
                {
                    "ticker": ["AAPL", "MSFT"],  # lowercase 'ticker' column
                    "weight": [0.5, 0.5],
                }
            )
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)

        # Test non-AI selection mode (default)
        portfolios = load_portfolios(excel_path, is_ai_selection=False)

        # Since there is no 'Ticker' column, this worksheet should be skipped.
        assert len(portfolios) == 0

    def test_mixed_valid_invalid_sheets(self, tmp_path):
        """Tests a mix of valid and invalid worksheets."""
        sheets_data = {
            "2022-01-01": pd.DataFrame({"Ticker": ["AAPL", "MSFT"]}),  # Valid
            "2022-04-01": pd.DataFrame(),  # Empty worksheet
            "2022-07-01": pd.DataFrame({"Symbol": ["GOOGL"]}),  # Incorrect column name
            "2022-10-01": pd.DataFrame({"Ticker": ["", "   ", None]}),  # All invalid tickers
            "2022-12-01": pd.DataFrame({"Ticker": ["TSLA", "NVDA"]}),  # Valid
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        # Only truly valid worksheets should be included.
        assert len(portfolios) == 2
        assert datetime.date(2022, 1, 1) in portfolios
        assert datetime.date(2022, 12, 1) in portfolios

        # Verify data content
        assert portfolios[datetime.date(2022, 1, 1)]["Ticker"].tolist() == [
            "AAPL",
            "MSFT",
        ]
        assert portfolios[datetime.date(2022, 12, 1)]["Ticker"].tolist() == [
            "TSLA",
            "NVDA",
        ]

    def test_preserve_additional_columns(self, tmp_path):
        """Tests the functionality of preserving additional columns."""
        sheets_data = {
            "2022-01-01": pd.DataFrame(
                {
                    "Ticker": ["AAPL", "MSFT"],
                    "Weight": [0.6, 0.4],
                    "Sector": ["Technology", "Technology"],
                    "Score": [0.85, 0.92],
                }
            )
        }

        excel_path = self.create_test_excel(tmp_path, sheets_data)
        portfolios = load_portfolios(excel_path)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]

        # All columns should be preserved.
        expected_columns = ["Ticker", "Weight", "Sector", "Score"]
        assert list(df.columns) == expected_columns

        # Verify data integrity.
        assert df["Weight"].tolist() == [0.6, 0.4]
        assert df["Sector"].tolist() == ["Technology", "Technology"]
        assert df["Score"].tolist() == [0.85, 0.92]

    def test_load_preliminary_json_directory(self, tmp_path):
        """Tests loading from a directory of preliminary selection JSON files."""
        data = {
            "schema_version": 1,
            "source": "preliminary",
            "trade_date": "2022-01-01",
            "rows": [
                {"ticker": "  aapl_DELISTED  ", "rank": 1},
                {"ticker": "MSFT", "rank": 2},
                {"ticker": "", "rank": 3},
            ],
        }
        year_dir = tmp_path / "2022"
        year_dir.mkdir()
        (year_dir / "2022-01-01.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

        portfolios = load_portfolios(tmp_path, is_ai_selection=False)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]
        assert df["Ticker"].tolist() == ["AAPL", "MSFT"]

    def test_load_ai_json_directory(self, tmp_path):
        """Tests loading from a directory of AI selection JSON files."""
        data = {
            "schema_version": 1,
            "source": "ai_pick",
            "trade_date": "2022-01-01",
            "picks": [
                {"ticker": "aapl", "confidence": 0.9},
                {"ticker": "MSFT_DELISTED", "confidence": 0.8},
                {"ticker": ""},
            ],
        }
        year_dir = tmp_path / "2022"
        year_dir.mkdir()
        (year_dir / "2022-01-01.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

        portfolios = load_portfolios(tmp_path, is_ai_selection=True)

        assert len(portfolios) == 1
        df = portfolios[datetime.date(2022, 1, 1)]
        assert df["Ticker"].tolist() == ["AAPL", "MSFT"]


class TestLoadPortfoliosIntegration:
    """Integration Tests: Simulating a real-world use case."""

    def test_quarterly_rebalancing_scenario(self, tmp_path):
        """Tests a quarterly rebalancing scenario."""
        # Simulate a portfolio for four quarters of a year.
        sheets_data = {
            "2022-01-03": pd.DataFrame(
                {"Ticker": ["AAPL", "MSFT", "GOOGL"], "Weight": [0.4, 0.3, 0.3]}
            ),
            "2022-04-01": pd.DataFrame(
                {
                    "Ticker": ["AAPL", "TSLA", "NVDA"],  # Rebalance: MSFT,GOOGL -> TSLA,NVDA
                    "Weight": [0.5, 0.25, 0.25],
                }
            ),
            "2022-07-01": pd.DataFrame(
                {
                    "Ticker": ["MSFT", "GOOGL", "AMZN"],  # Complete turnover
                    "Weight": [0.33, 0.33, 0.34],
                }
            ),
            "2022-10-03": pd.DataFrame(
                {
                    "Ticker": ["SPY"],  # Switch to index investing
                    "Weight": [1.0],
                }
            ),
        }

        excel_path = tmp_path / "quarterly_portfolios.xlsx"
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets_data.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        portfolios = load_portfolios(excel_path)

        # Verify that all quarters are loaded correctly.
        assert len(portfolios) == 4

        expected_dates = [
            datetime.date(2022, 1, 3),
            datetime.date(2022, 4, 1),
            datetime.date(2022, 7, 1),
            datetime.date(2022, 10, 3),
        ]

        for date in expected_dates:
            assert date in portfolios

        # Verify the number of stocks for each quarter.
        assert len(portfolios[datetime.date(2022, 1, 3)]) == 3
        assert len(portfolios[datetime.date(2022, 4, 1)]) == 3
        assert len(portfolios[datetime.date(2022, 7, 1)]) == 3
        assert len(portfolios[datetime.date(2022, 10, 3)]) == 1

        # Verify the data for the last quarter.
        final_portfolio = portfolios[datetime.date(2022, 10, 3)]
        assert final_portfolio["Ticker"].iloc[0] == "SPY"
        assert final_portfolio["Weight"].iloc[0] == 1.0
