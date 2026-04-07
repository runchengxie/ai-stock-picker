import pytest

from stock_analysis.execution.broker.longport_client import _to_lb_symbol


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expect",
    [
        ("AAPL", "AAPL.US"),
        ("MSFT", "MSFT.US"),
        ("700.HK", "700.HK"),
        ("TSLA.US", "TSLA.US"),
        ("aapl", "AAPL.US"),
        ("  GOOGL  ", "GOOGL.US"),
        ("BABA.HK", "BABA.HK"),
        ("SE.SG", "SE.SG"),
        ("nvda", "NVDA.US"),
        ("\tAMZN\n", "AMZN.US"),  # Test various whitespace characters
    ],
)
def test_to_lb_symbol(raw, expect):
    """Tests the function that converts a stock symbol to the LongPort format.

    Test rules:
    - Defaults to appending the .US suffix.
    - Symbols that already have a .US, .HK, or .SG suffix are left unchanged.
    - Automatically converts the symbol to uppercase.
    - Strips leading and trailing whitespace.
    """
    assert _to_lb_symbol(raw) == expect


@pytest.mark.unit
def test_to_lb_symbol_edge_cases():
    """Tests edge cases for the symbol conversion function."""
    # An empty string should return ".US"
    assert _to_lb_symbol("") == ".US"

    # A string containing only spaces
    assert _to_lb_symbol("   ") == ".US"

    # Test mixed-case inputs
    assert _to_lb_symbol("TsLa.us") == "TSLA.US"
    assert _to_lb_symbol("baba.hk") == "BABA.HK"
    assert _to_lb_symbol("se.sg") == "SE.SG"
