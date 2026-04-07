import os
from datetime import date, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_api]

# Try to import longport, skip all tests if it fails
longport = pytest.importorskip("longport")

from stock_analysis.execution.broker.longport_client import LongPortClient, get_config


def check_longport_credentials():
    """Check if LongPort API credentials are configured."""
    required_vars = ["LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN"]
    return all(os.getenv(var) for var in required_vars)

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_get_config_from_env():
    """Test getting LongPort configuration from environment variables."""
    config = get_config()
    assert config is not None
    # Do not directly check credential content, only verify successful creation of the config object

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_longport_client_initialization():
    """Test LongPortClient initialization."""
    try:
        client = LongPortClient()
        assert client.cfg is not None
        assert client.q is not None
        assert client.t is not None
    except Exception as e:
        # Network/endpoint issues should not fail the suite
        if "network" in str(e).lower() or "timeout" in str(e).lower() or "connect" in str(e).lower():
            pytest.skip(f"Network/endpoint issue, skipping: {e}")
        pytest.fail(f"LongPortClient initialization failed: {e}")

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_quote_last_real_api():
    """Test getting stock quotes from the real API.

    Note: This test calls the real LongPort API and requires
    valid API credentials and a network connection.
    """
    # Use common US stocks for testing
    test_tickers = ["AAPL", "MSFT"]

    try:
        client = LongPortClient()
        quotes = client.quote_last(test_tickers)

        # Verify the structure of the returned result
        assert isinstance(quotes, dict)
        assert len(quotes) <= len(test_tickers)  # Some stocks might not be in trading hours

        for symbol, (price, timestamp) in quotes.items():
            # Verify data types and reasonableness
            assert isinstance(symbol, str)
            assert symbol.endswith((".US", ".HK", ".SG"))
            assert isinstance(price, int | float)
            assert price > 0  # Stock price should be positive
            assert isinstance(timestamp, int)
            assert timestamp > 0  # Timestamp should be positive

    except Exception as e:
        # If it's a network error or API limit, provide a more user-friendly error message
        if "network" in str(e).lower() or "timeout" in str(e).lower() or "connect" in str(e).lower():
            pytest.skip(f"Network connection issue, skipping test: {e}")
        elif "rate limit" in str(e).lower() or "quota" in str(e).lower():
            pytest.skip(f"API limit reached, skipping test: {e}")
        else:
            pytest.fail(f"Failed to get quotes: {e}")

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_candles_real_api():
    """Test getting historical candlestick data from the real API.

    Note: This test calls the real LongPort API.
    """
    # Get data for the last 30 days
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    try:
        client = LongPortClient()
        candles = client.candles("AAPL", start_date, end_date)

        # Verify the returned result
        assert candles is not None
        # Specific data structure verification depends on the format returned by the longport library
        # Here, we only perform a basic non-null check

    except Exception as e:
        if "network" in str(e).lower() or "timeout" in str(e).lower() or "connect" in str(e).lower():
            pytest.skip(f"Network connection issue, skipping test: {e}")
        elif "rate limit" in str(e).lower() or "quota" in str(e).lower():
            pytest.skip(f"API limit reached, skipping test: {e}")
        elif "market closed" in str(e).lower() or "no data" in str(e).lower():
            pytest.skip(f"Market closed or no data, skipping test: {e}")
        else:
            pytest.fail(f"Failed to get candlestick data: {e}")

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_symbol_conversion_integration():
    """Test symbol conversion behavior in real API calls."""
    client = LongPortClient()

    # Test different formats of stock tickers
    test_cases = [
        "AAPL",       # Should be converted to AAPL.US
        "MSFT.US",    # Should remain unchanged
        "700.HK",     # Should remain unchanged (if permission is granted)
    ]

    for ticker in test_cases:
        try:
            quotes = client.quote_last([ticker])
            # If data is successfully retrieved, verify the format of the returned symbol
            for symbol in quotes.keys():
                assert symbol.endswith((".US", ".HK", ".SG")), (
                    f"Incorrect symbol format: {symbol}"
                )

        except Exception as e:
            # It's normal to not have permission for some markets or for them to be outside trading hours
            if (
                "network" in str(e).lower()
                or "timeout" in str(e).lower()
                or "connect" in str(e).lower()
            ):
                pytest.skip(f"Network connection issue, skipping: {e}")
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                pytest.skip(f"No permission to access {ticker}, skipping: {e}")
            elif "not found" in str(e).lower() or "invalid" in str(e).lower():
                pytest.skip(f"Ticker {ticker} is invalid or not found, skipping: {e}")
            else:
                # Other errors might require attention
                pytest.fail(f"Error while testing {ticker}: {e}")

@pytest.mark.skipif(
    not check_longport_credentials(), reason="LongPort API credentials are not configured, skipping integration tests"
)
def test_api_error_handling():
    """Test API error handling."""
    # Test with invalid stock tickers
    invalid_tickers = ["INVALID_TICKER_12345"]

    try:
        client = LongPortClient()
        quotes = client.quote_last(invalid_tickers)
        # If no exception is thrown, check if the result is empty or contains an error message
        assert isinstance(quotes, dict)

    except Exception as e:
        # An error is expected, which is normal
        if "network" in str(e).lower() or "timeout" in str(e).lower() or "connect" in str(e).lower():
            pytest.skip(f"Network connection issue, skipping test: {e}")
        else:
            assert (
                "invalid" in str(e).lower()
                or "not found" in str(e).lower()
                or "error" in str(e).lower()
            )


# Note: The submit_limit method involves real trading and is not tested in integration tests.
# Real trading tests should be conducted in a dedicated trading test environment, not in CI/CD.
