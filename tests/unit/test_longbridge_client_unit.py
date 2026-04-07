from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from stock_analysis.execution.broker.longport_client import LongPortClient


@pytest.mark.unit
def test_quote_last_mapping():
    """Test the data mapping logic of the quote_last method."""
    # Create fake response data
    fake_resp = [
        SimpleNamespace(symbol="AAPL.US", last_done=189.5, timestamp=1234567890),
        SimpleNamespace(symbol="MSFT.US", last_done=350.2, timestamp=1234567891),
    ]

    # Create a mock QuoteContext
    mock_quote_context = Mock()
    mock_quote_context.quote.return_value = fake_resp

    # Create a client instance and replace the QuoteContext
    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = mock_quote_context
        client.t = Mock()  # TradeContext also needs to be mocked

        # Test the method call
        result = client.quote_last(["AAPL", "MSFT"])

        # Verify the call arguments
        mock_quote_context.quote.assert_called_once_with(["AAPL.US", "MSFT.US"])

        # Verify the return result
        assert result == {
            "AAPL.US": (189.5, 1234567890),
            "MSFT.US": (350.2, 1234567891),
        }


@pytest.mark.unit
def test_candles_parameters():
    """Test the parameter passing for the candles method."""
    mock_quote_context = Mock()
    mock_quote_context.history_candlesticks_by_date.return_value = []

    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = mock_quote_context
        client.t = Mock()

        start_date = date(2023, 1, 1)
        end_date = date(2023, 12, 31)
        custom_period = Mock()

        # Test the method call - the focus is to verify that _to_lb_symbol is
        # called correctly and parameters are passed
        client.candles("AAPL", start_date, end_date, custom_period)

        # Verify that history_candlesticks_by_date was called
        mock_quote_context.history_candlesticks_by_date.assert_called_once()
        call_args = mock_quote_context.history_candlesticks_by_date.call_args

        # Verify the first argument is the converted symbol
        assert call_args[0][0] == "AAPL.US"
        # Verify the date parameters
        assert call_args[0][3] == start_date
        assert call_args[0][4] == end_date
        # Verify the period parameter
        assert call_args[0][1] == custom_period


@pytest.mark.unit
def test_submit_limit_buy_order():
    """Test submitting a buy limit order."""
    from stock_analysis.execution.broker._stubs import (
        OrderSide,
        OrderType,
        TimeInForceType,
    )

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="12345")

    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        # Test a buy order (positive quantity)
        result = client.submit_limit("AAPL", 150.0, 100)

        mock_trade_context.submit_order.assert_called_with(
            symbol="AAPL.US",
            order_type=OrderType.LO,
            side=OrderSide.Buy,
            submitted_price=Decimal("150.0"),
            submitted_quantity=Decimal("100"),
            time_in_force=TimeInForceType.Day,
            remark=None,
        )

        assert result.order_id == "12345"


@pytest.mark.unit
def test_submit_limit_sell_order():
    """Test submitting a sell limit order."""
    from stock_analysis.execution.broker._stubs import (
        OrderSide,
        OrderType,
        TimeInForceType,
    )

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="67890")

    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        # Test a sell order (negative quantity)
        result = client.submit_limit("MSFT", 300.0, -50, remark="test sell")

        mock_trade_context.submit_order.assert_called_with(
            symbol="MSFT.US",
            order_type=OrderType.LO,
            side=OrderSide.Sell,
            submitted_price=Decimal("300.0"),
            submitted_quantity=Decimal("50"),  # must be the absolute value
            time_in_force=TimeInForceType.Day,
            remark="test sell",
        )

        assert result.order_id == "67890"


@pytest.mark.unit
def test_submit_limit_with_custom_tif():
    """Test a limit order with a custom time-in-force (TIF)."""
    # Use mock objects to avoid importing longbridge enums
    mock_order_type = Mock()
    mock_order_side = Mock()
    mock_tif_gtc = Mock()

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="11111")

    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        with patch("stock_analysis.execution.broker.longport_client.OrderType") as mock_ot:
            with patch("stock_analysis.execution.broker.longport_client.OrderSide") as mock_os:
                with patch(
                    "stock_analysis.execution.broker.longport_client.TimeInForceType"
                ) as mock_tif:
                    mock_ot.LO = mock_order_type
                    mock_os.Buy = mock_order_side
                    mock_tif.GTC = mock_tif_gtc

                    client = LongPortClient.__new__(LongPortClient)
                    client.q = Mock()
                    client.t = mock_trade_context

                    # Test a GTC (Good 'Til Canceled) order
                    client.submit_limit("GOOGL", 2500.0, 10, mock_tif_gtc)

                    mock_trade_context.submit_order.assert_called_with(
                        symbol="GOOGL.US",
                        order_type=mock_order_type,
                        side=mock_order_side,
                        submitted_price=Decimal("2500.0"),
                        submitted_quantity=Decimal("10"),
                        time_in_force=mock_tif_gtc,
                        remark=None,
                    )


@pytest.mark.unit
def test_decimal_precision():
    """Test the Decimal precision handling for price and quantity."""

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="22222")

    with patch("stock_analysis.execution.broker.longport_client.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        # Test floating point precision
        client.submit_limit("TSLA", 199.99, 25)

        # Verify the Decimal conversion
        call_args = mock_trade_context.submit_order.call_args
        assert call_args.kwargs["submitted_price"] == Decimal("199.99")
        assert call_args.kwargs["submitted_quantity"] == Decimal("25")
        assert isinstance(call_args.kwargs["submitted_price"], Decimal)
        assert isinstance(call_args.kwargs["submitted_quantity"], Decimal)


@pytest.mark.unit
def test_portfolio_snapshot_basic(monkeypatch):
    cash_info = SimpleNamespace(currency="HKD", available_cash=2000.0)
    asset_obj = SimpleNamespace(
        cash_infos=[cash_info], net_assets=2000.0, currency="HKD"
    )
    pos1 = SimpleNamespace(symbol="AAPL.US", quantity=10, market="US")
    pos2 = SimpleNamespace(symbol="TSLA.US", quantity=5, market="US")
    mock_trade = Mock()
    mock_trade.asset.return_value = [asset_obj]
    mock_trade.stock_positions.return_value = [pos1, pos2]

    client = LongPortClient.__new__(LongPortClient)
    client.trade = mock_trade
    client.quote = Mock()

    monkeypatch.setenv("FX_HKD_USD", "0.25")

    cash_usd, pos_map, net_assets, base_ccy = client.portfolio_snapshot()
    assert cash_usd == pytest.approx(500.0)
    assert pos_map == {"AAPL.US": 10, "TSLA.US": 5}
    assert net_assets == 2000.0
    assert base_ccy == "HKD"
