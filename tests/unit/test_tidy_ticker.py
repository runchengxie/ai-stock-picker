"""Unit tests for the tidy_ticker function.

Tests the core functionality of the data cleaning function:
- Case normalization
- Whitespace handling
- Suffix removal (e.g., _DELISTED)
- Null value handling
- Idempotency validation
"""

import pandas as pd
import pytest

from stock_analysis.research.data.load_data_to_db import tidy_ticker


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expect",
    [
        # Basic test cases provided by the user
        ([" aapl ", "MSFT_DELISTED", "", None], ["AAPL", "MSFT", pd.NA, pd.NA]),
        (["\tspy\n", "googl_delisted", "Se  "], ["SPY", "GOOGL", "SE"]),
        # Extended test cases
        # Test various whitespace characters
        (["  AMZN  ", "\t\nTSLA\r\n", "   "], ["AMZN", "TSLA", pd.NA]),
        # Test mixed case
        (["AaPl", "mSfT", "GoOgL"], ["AAPL", "MSFT", "GOOGL"]),
        # Test various _DELISTED suffixes
        (
            ["AAPL_DELISTED", "msft_delisted", "GOOGL_Delisted"],
            ["AAPL", "MSFT", "GOOGL"],
        ),
        # Test combined cases (whitespace, case, and suffix)
        (
            [" aapl_delisted ", "\tMSFT_DELISTED\n", "  googl  "],
            ["AAPL", "MSFT", "GOOGL"],
        ),
        # Test edge cases
        (["A", "AB", "ABC"], ["A", "AB", "ABC"]),  # Short ticker symbols
        (["BERKSHIRE.A", "BRK.B"], ["BERKSHIRE.A", "BRK.B"]),  # Containing dots
        # Test various forms of null values
        (["", "   ", "\t\n", None], [pd.NA, pd.NA, pd.NA, pd.NA]),
    ],
)
def test_tidy_ticker_basic(raw, expect):
    """Tests the basic functionality of tidy_ticker."""
    out = tidy_ticker(pd.Series(raw)).tolist()

    # Handle comparison with pd.NA
    for i, (actual, expected) in enumerate(zip(out, expect, strict=False)):
        if pd.isna(expected):
            assert pd.isna(actual), f"Index {i}: expected NA, got {actual}"
        else:
            assert actual == expected, f"Index {i}: expected {expected}, got {actual}"


@pytest.mark.unit
def test_tidy_ticker_idempotent():
    """Tests the idempotency of tidy_ticker: tidy(tidy(x)) == tidy(x)."""
    # User-provided test case
    s = pd.Series([" amzn_deListed ", "  "])
    once = tidy_ticker(s)
    twice = tidy_ticker(once)
    pd.testing.assert_series_equal(once, twice, check_names=False)

    # Extended idempotency tests
    test_cases = [
        [" AAPL ", "MSFT_delisted", "", "GOOGL", None],
        ["\tTSLA\n", "amzn_DELISTED", "   ", "NVDA"],
        ["already_clean", "ALSO_CLEAN", "clean_delisted"],
        # Already cleaned data
        ["AAPL", "MSFT", "GOOGL"],
    ]

    for case in test_cases:
        original = pd.Series(case)
        first_clean = tidy_ticker(original)
        second_clean = tidy_ticker(first_clean)

        (
            pd.testing.assert_series_equal(
                first_clean, second_clean, check_names=False
            ),
            f"Idempotency failed for case: {case}",
        )


@pytest.mark.unit
class TestTidyTickerProperties:
    """Tests the properties of the tidy_ticker function."""

    def test_only_affects_whitespace_case_suffix(self):
        """Tests that the function only affects whitespace, case, and the specified suffix, without altering other characters."""
        # Ticker symbols containing special characters that should not be changed
        test_cases = [
            "BRK.A",  # Dot should be preserved
            "BRK-B",  # Hyphen should be preserved
            "SOME123",  # Numbers should be preserved
            "ABC&DEF",  # Special symbols should be preserved (except for the handled suffix)
        ]

        for case in test_cases:
            # Add elements that require cleaning
            dirty = f"  {case.lower()}_delisted  "
            cleaned = tidy_ticker(pd.Series([dirty]))[0]

            # The result should be the original characters in uppercase (with suffix removed)
            expected = case.upper()
            assert cleaned == expected, f"Expected {expected}, got {cleaned}"

    def test_preserves_series_length(self):
        """Tests that the function preserves the length of the Series."""
        test_series = pd.Series(["AAPL", " MSFT ", "googl_delisted", "", None, "\t\n"])

        result = tidy_ticker(test_series)
        assert len(result) == len(test_series)

    def test_handles_empty_series(self):
        """Tests handling of an empty Series."""
        empty_series = pd.Series([], dtype="object")
        result = tidy_ticker(empty_series)

        assert len(result) == 0
        assert result.dtype == "string"

    def test_consistent_output_type(self):
        """Tests for consistent output data type."""
        test_cases = [
            ["AAPL", "MSFT"],
            [" aapl ", "msft_delisted"],
            ["", None],
            ["mixed", " CASE ", "test_delisted", ""],
        ]

        for case in test_cases:
            result = tidy_ticker(pd.Series(case))
            assert result.dtype == "string", f"Wrong dtype for case {case}"

    def test_delisted_suffix_variations(self):
        """Tests the handling of various _DELISTED suffix casings."""
        variations = [
            "AAPL_DELISTED",
            "aapl_delisted",
            "Aapl_Delisted",
            "AAPL_delisted",
            "aapl_DELISTED",
        ]

        results = tidy_ticker(pd.Series(variations))

        # All variations should be cleaned to "AAPL"
        for result in results:
            assert result == "AAPL", f"Failed to clean delisted suffix: {result}"

    def test_no_false_positive_delisted_removal(self):
        """Tests that the function does not incorrectly remove 'DELISTED' when it is not a suffix."""
        # These should not be treated as suffixes
        false_positives = [
            "DELISTED_CORP",  # Prefix, not a suffix
            "SOME_DELISTED_CO",  # In the middle, not a suffix
            "DELISTED",  # The entire name, not a suffix
        ]

        results = tidy_ticker(pd.Series(false_positives))
        expected = ["DELISTED_CORP", "SOME_DELISTED_CO", "DELISTED"]

        for result, expect in zip(results, expected, strict=False):
            assert result == expect, f"Incorrectly removed DELISTED from {result}"


@pytest.mark.unit
class TestTidyTickerEdgeCases:
    """Tests edge cases and exceptional scenarios."""

    def test_very_long_ticker(self):
        """Tests a very long ticker symbol."""
        long_ticker = "A" * 50 + "_DELISTED"
        result = tidy_ticker(pd.Series([long_ticker]))[0]
        assert result == "A" * 50

    def test_unicode_characters(self):
        """Tests the handling of Unicode characters."""
        unicode_tickers = ["AAPL™", "MSFT®", "GOOGL©"]
        results = tidy_ticker(pd.Series(unicode_tickers))

        # Unicode characters should be preserved
        expected = ["AAPL™", "MSFT®", "GOOGL©"]
        for result, expect in zip(results, expected, strict=False):
            assert result == expect

    def test_multiple_underscores(self):
        """Tests cases with multiple underscores."""
        test_cases = [
            "AAPL__DELISTED",  # Double underscore
            "AAPL_TEST_DELISTED",  # Underscore in the middle
            "AAPL_DELISTED_",  # Trailing underscore
        ]

        results = tidy_ticker(pd.Series(test_cases))

        # Only the trailing _DELISTED should be removed
        expected = ["AAPL_", "AAPL_TEST", "AAPL_DELISTED_"]
        for result, expect in zip(results, expected, strict=False):
            assert result == expect, f"Expected {expect}, got {result}"

    def test_mixed_data_types_in_series(self):
        """Tests handling of a Series with mixed data types."""
        # Although the series should ideally contain only strings in practice, this tests robustness.
        mixed_series = pd.Series(["AAPL", None, "", 123, "MSFT_delisted"])

        # The function should handle this without crashing.
        result = tidy_ticker(mixed_series)
        assert len(result) == 5

        # Check that string elements are processed correctly.
        assert result.iloc[0] == "AAPL"
        assert pd.isna(result.iloc[1])
        assert pd.isna(result.iloc[2])
        # Numbers will be converted to strings.
        assert result.iloc[3] == "123"
        assert result.iloc[4] == "MSFT"
