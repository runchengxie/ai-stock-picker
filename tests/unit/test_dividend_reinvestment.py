import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pandas.testing as pdt
import pytest
from stock_analysis.research.backtest.engine import run_quarterly_backtest
from stock_analysis.research.backtest.prep import DividendPandasData

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def mock_risk_free_service():
    """Patch risk-free service for deterministic Sharpe calculations."""

    with patch("stock_analysis.research.backtest.engine._get_risk_free_service") as mock_factory:
        service = MagicMock()
        service.default_series = "DGS3MO"

        def _compute_sharpe(returns: pd.Series) -> float | None:
            if isinstance(returns, pd.Series) and not returns.empty:
                return 0.5
            return None

        service.compute_sharpe.side_effect = _compute_sharpe
        mock_factory.return_value = service
        yield service


def test_dividend_reinvestment():
    index = pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"])
    price = pd.DataFrame(
        {
            "Open": [100, 100, 100],
            "High": [100, 100, 100],
            "Low": [100, 100, 100],
            "Close": [100, 100, 100],
            "Volume": [1000, 1000, 1000],
            "Dividend": [0.0, 1.0, 0.0],
        },
        index=index,
    )

    feed = DividendPandasData(dataname=price, openinterest=None, name="TEST")
    portfolios = {datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["TEST"]})}

    portfolio_value, metrics = run_quarterly_backtest(
        portfolios,
        {"TEST": feed},
        initial_cash=100,
        start_date=datetime.date(2022, 1, 3),
        end_date=datetime.date(2022, 1, 5),
        use_logging=False,
    )

    expected_index = pd.to_datetime(
        ["2022-01-02", "2022-01-03", "2022-01-04", "2022-01-05"]
    )
    expected = pd.Series([100.0, 100.0, 100.0, 101.0], index=expected_index)

    pdt.assert_series_equal(portfolio_value, expected)
    assert metrics["sharpe"] == 0.5
    assert metrics["risk_free_series"] == "DGS3MO"
