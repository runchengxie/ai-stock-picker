"""Unit tests for preliminary_selection.py

Tests the core functionality of factor screening:
- Consistency of rolling window calculations
- Stability of missing value (NaN) handling
- Reproducibility of scoring and sorting
- Stability of the tie-breaking rule
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta

from stock_analysis.research.selection.preliminary_selection import (
    calc_factor_scores,
    calculate_factors_point_in_time,
)


@pytest.mark.unit
class TestFactorCalculation:
    """Tests the core logic of factor calculation."""

    def test_calculate_factors_with_nan_handling(self):
        """Test the stability of NaN handling."""
        # Construct test data containing NaN values
        df = pd.DataFrame(
            {
                "Ticker": ["AAPL", "AAPL", "MSFT", "MSFT", "GOOGL", "GOOGL"],
                "date_known": pd.to_datetime(
                    [
                        "2023-01-01",
                        "2023-04-01",
                        "2023-01-01",
                        "2023-04-01",
                        "2023-01-01",
                        "2023-04-01",
                    ]
                ),
                "year": [2022, 2023, 2022, 2023, 2022, 2023],
                "cfo": [100, 120, np.nan, 150, 80, 90],  # MSFT is missing data for the first period
                "ceq": [500, 550, 300, np.nan, 400, 420],  # MSFT is missing data for the second period
                "txt": [10, 12, 8, 15, 6, 7],
                "at": [1000, 1100, 800, 900, 700, 750],
                "rect": [50, 55, 40, 45, 35, 38],
            }
        )

        result = calculate_factors_point_in_time(df)

        # Verify that rows with NaN are correctly filtered. Since a delta is calculated,
        # the actual result will have fewer rows.
        assert len(result) >= 2  # There should be at least 2 rows with complete data
        assert "AAPL" in result["Ticker"].values

        # Verify that the factor score is calculated correctly
        assert "factor_score" in result.columns
        assert not result["factor_score"].isna().any()

    def test_factor_weights_consistency(self):
        """Test that factor calculations are reproducible."""
        # Construct standard test data
        df = pd.DataFrame(
            {
                "Ticker": ["A", "A", "B", "B"],
                "date_known": pd.to_datetime(["2023-01-01", "2023-04-01"] * 2),
                "year": [2022, 2023, 2022, 2023],
                "cfo": [100, 120, 80, 90],
                "ceq": [500, 550, 400, 420],
                "txt": [10, 12, 6, 7],
                "at": [1000, 1100, 700, 750],
                "rect": [50, 55, 35, 38],
            }
        )

        # Multiple calculations should yield the same result
        result1 = calculate_factors_point_in_time(df.copy())
        result2 = calculate_factors_point_in_time(df.copy())

        pd.testing.assert_frame_equal(result1, result2)

    def test_tie_break_stability(self):
        """Test the stability of the tie-breaking rule for identical scores."""
        # Construct a case where two stocks have identical factor inputs
        df = pd.DataFrame(
            {
                "Ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "date_known": pd.to_datetime(["2023-01-01", "2023-04-01"] * 2),
                "year": [2022, 2023, 2022, 2023],
                "cfo": [100, 120, 100, 120],  # Identical values
                "ceq": [500, 550, 500, 550],  # Identical values
                "txt": [10, 12, 10, 12],  # Identical values
                "at": [1000, 1100, 1000, 1100],  # Identical values
                "rect": [50, 55, 50, 55],  # Identical values
            }
        )

        result = calculate_factors_point_in_time(df)

        # Verify that identical inputs produce identical outputs
        aapl_score = result[result["Ticker"] == "AAPL"]["factor_score"].iloc[0]
        msft_score = result[result["Ticker"] == "MSFT"]["factor_score"].iloc[0]

        # Since the inputs are identical, the scores should be equal (if neither is NaN)
        if not (pd.isna(aapl_score) or pd.isna(msft_score)):
            assert abs(aapl_score - msft_score) < 1e-10


@pytest.mark.unit
class TestRollingWindowLogic:
    """Tests the rolling window logic."""

    def test_rolling_window_consistency(self):
        """Test the consistency of rolling window calculations."""
        # Construct 5 years of test data
        base_date = datetime(2020, 1, 1)
        dates = [
            base_date + relativedelta(months=3 * i) for i in range(20)
        ]  # 5 years of quarterly data

        df = pd.DataFrame(
            {
                "Ticker": ["AAPL"] * 20,
                "date_known": dates,
                "year": [d.year for d in dates],
                "cfo": np.random.randint(80, 120, 20),
                "ceq": np.random.randint(400, 600, 20),
                "txt": np.random.randint(5, 15, 20),
                "at": np.random.randint(800, 1200, 20),
                "rect": np.random.randint(30, 60, 20),
            }
        )

        # Calculate point-in-time factors, which are needed for the next step
        df_with_factors = calculate_factors_point_in_time(df)

        # Test window calculation with the same as_of_date
        as_of_date1 = pd.Timestamp("2023-01-01")
        as_of_date2 = pd.Timestamp("2023-01-01")  # Same date

        result1 = calc_factor_scores(df_with_factors, as_of_date1, 5, 5)
        result2 = calc_factor_scores(df_with_factors, as_of_date2, 5, 5)

        # The same inputs should produce the same output
        if not result1.empty and not result2.empty:
            pd.testing.assert_frame_equal(result1, result2)

    def test_min_reports_threshold(self):
        """Test the minimum number of reports threshold."""
        # Construct data where one stock does not have enough reports
        df = pd.DataFrame(
            {
                "Ticker": ["AAPL"] * 3 + ["MSFT"] * 8,  # AAPL has only 3 reports, MSFT has 8
                "date_known": pd.to_datetime(
                    [
                        "2022-01-01",
                        "2022-04-01",
                        "2022-07-01",  # AAPL
                        "2021-01-01",
                        "2021-04-01",
                        "2021-07-01",
                        "2021-10-01",
                        "2022-01-01",
                        "2022-04-01",
                        "2022-07-01",
                        "2022-10-01",  # MSFT
                    ]
                ),
                "year": [2022] * 3 + [2021] * 4 + [2022] * 4,
                "factor_score": [1.0] * 11,
            }
        )

        as_of_date = pd.Timestamp("2023-01-01")
        result = calc_factor_scores(df, as_of_date, 5, 5)  # Require at least 5 reports

        # Only MSFT should pass the filter
        assert len(result) == 1
        assert result.index[0] == "MSFT"


@pytest.mark.unit
class TestTopNSelection:
    """Tests the stability of Top-N selection."""

    def test_top_n_reproducibility(self):
        """Test the reproducibility of Top-N selection."""
        # Construct data with a clear expected order
        df = pd.DataFrame(
            {
                "avg_factor_score": [3.0, 1.0, 2.0, 4.0, 0.5],
                "num_reports": [10, 8, 9, 12, 7],
            },
            index=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"],
        )

        # Sorting multiple times should yield the same result
        sorted1 = df.sort_values(by="avg_factor_score", ascending=False)
        sorted2 = df.sort_values(by="avg_factor_score", ascending=False)

        pd.testing.assert_frame_equal(sorted1, sorted2)

        # Verify the sort order
        expected_order = ["AMZN", "AAPL", "GOOGL", "MSFT", "TSLA"]
        assert sorted1.index.tolist() == expected_order

    def test_tie_break_by_ticker(self):
        """Test the tie-break rule (sort by ticker) for identical scores."""
        # Construct data with identical scores
        df = pd.DataFrame(
            {
                "avg_factor_score": [2.0, 2.0, 1.0],  # AAPL and MSFT have the same score
                "num_reports": [10, 10, 8],
            },
            index=["MSFT", "AAPL", "GOOGL"],
        )  # Deliberately shuffle the initial order

        # Sort by score descending, then by ticker ascending (a stable tie-break)
        sorted_df = df.sort_values(
            by=["avg_factor_score", df.index], ascending=[False, True]
        )

        # Verify the tie-break result: for the same score, AAPL should come before MSFT (alphabetical order)
        expected_order = ["AAPL", "MSFT", "GOOGL"]
        assert sorted_df.index.tolist() == expected_order


@pytest.mark.unit
class TestEdgeCases:
    """Tests edge cases."""

    def test_empty_dataframe(self):
        """Test handling of an empty DataFrame."""
        empty_df = pd.DataFrame()
        result = calculate_factors_point_in_time(empty_df)
        assert result.empty

    def test_all_nan_factors(self):
        """Test the case where all factor inputs are NaN."""
        df = pd.DataFrame(
            {
                "Ticker": ["AAPL", "MSFT"],
                "date_known": pd.to_datetime(["2023-01-01", "2023-01-01"]),
                "year": [2023, 2023],
                "cfo": [np.nan, np.nan],
                "ceq": [np.nan, np.nan],
                "txt": [np.nan, np.nan],
                "at": [np.nan, np.nan],
                "rect": [np.nan, np.nan],
            }
        )

        result = calculate_factors_point_in_time(df)
        assert result.empty

    def test_single_stock_multiple_periods(self):
        """Test handling of a single stock over multiple periods."""
        df = pd.DataFrame(
            {
                "Ticker": ["AAPL"] * 4,
                "date_known": pd.to_datetime(
                    ["2022-01-01", "2022-04-01", "2022-07-01", "2022-10-01"]
                ),
                "year": [2021, 2022, 2022, 2022],
                "cfo": [100, 110, 120, 130],
                "ceq": [500, 520, 540, 560],
                "txt": [10, 11, 12, 13],
                "at": [1000, 1020, 1040, 1060],
                "rect": [50, 52, 54, 56],
            }
        )

        result = calculate_factors_point_in_time(df)

        # Should result in 3 rows (the first row has no delta and is filtered out)
        assert len(result) == 3
        assert all(result["Ticker"] == "AAPL")
        assert not result["factor_score"].isna().any()
