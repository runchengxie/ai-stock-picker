"""Tests for the core behavior of the backtesting engine module.

Tests the core functionality of the backtesting engine in backtest.engine, including:
- Rebalance date alignment: Rebalancing only on each rebalance day and holding until
  the start of the next quarter.
- Cash initialization and ensuring the cumulative value curve output is not empty.
- Support for passing parameters for optional benchmark plotting.
- Graceful degradation and logging warnings when there is no data or partial
  stock data is missing.
"""

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
bt = pytest.importorskip("backtrader")
from stock_analysis.research.backtest.engine import (
    BuyAndHoldStrategy,
    PointInTimeStrategy,
    generate_report,
    run_benchmark_backtest,
    run_quarterly_backtest,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def mock_risk_free_service():
    """Patch the risk-free service to avoid network/database dependencies."""

    with patch("stock_analysis.research.backtest.engine._get_risk_free_service") as mock_factory:
        service = MagicMock()

        def _compute_sharpe(returns: pd.Series) -> float | None:
            if isinstance(returns, pd.Series) and not returns.empty:
                return 0.5
            return None

        service.compute_sharpe.side_effect = _compute_sharpe
        service.default_series = "DGS3MO"
        mock_factory.return_value = service
        yield service

class TestPointInTimeStrategy:
    """Tests for the PointInTimeStrategy class."""

    def create_mock_data_feed(
        self, ticker: str, dates: list, prices: list
    ) -> bt.feeds.PandasData:
        """Creates a mock data feed.

        Args:
            ticker: The stock ticker.
            dates: A list of dates.
            prices: A list of prices.

        Returns:
            bt.feeds.PandasData: A Backtrader data feed.
        """
        data = pd.DataFrame(
            {
                "Open": prices,
                "High": [p * 1.02 for p in prices],
                "Low": [p * 0.98 for p in prices],
                "Close": prices,
                "Volume": [1000000] * len(prices),
                "Dividend": [0.0] * len(prices),
            },
            index=pd.to_datetime(dates),
        )

        return bt.feeds.PandasData(dataname=data, name=ticker)

    def test_rebalance_date_alignment(self):
        """Tests the rebalance date alignment logic."""
        # Create a test portfolio.
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL", "MSFT"]}),
            datetime.date(2022, 4, 1): pd.DataFrame({"Ticker": ["GOOGL", "TSLA"]}),
            datetime.date(2022, 7, 1): pd.DataFrame({"Ticker": ["AMZN", "META"]}),
        }

        # Create a strategy instance.
        strategy = PointInTimeStrategy()
        strategy.p.portfolios = portfolios
        strategy.p.use_logging = False

        # Initialize the strategy.
        strategy.__init__()

        # Verify the sorting of rebalance dates.
        expected_dates = [
            datetime.date(2022, 1, 3),
            datetime.date(2022, 4, 1),
            datetime.date(2022, 7, 1),
        ]
        assert strategy.rebalance_dates == expected_dates

        # Verify the initial state.
        assert strategy.next_rebalance_idx == 0
        assert strategy.next_rebalance_date == datetime.date(2022, 1, 3)

    def test_get_next_rebalance_date(self):
        """Tests the logic for getting the next rebalance date."""
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL"]}),
            datetime.date(2022, 4, 1): pd.DataFrame({"Ticker": ["MSFT"]}),
        }

        strategy = PointInTimeStrategy()
        strategy.p.portfolios = portfolios
        strategy.__init__()

        # Initial state.
        assert strategy.next_rebalance_date == datetime.date(2022, 1, 3)

        # Move to the next date.
        strategy.next_rebalance_idx = 1
        strategy.get_next_rebalance_date()
        assert strategy.next_rebalance_date == datetime.date(2022, 4, 1)

        # Out of bounds.
        strategy.next_rebalance_idx = 2
        strategy.get_next_rebalance_date()
        assert strategy.next_rebalance_date is None

    def test_missing_tickers_handling(self):
        """Tests the handling of missing tickers."""
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame(
                {"Ticker": ["AAPL", "MISSING_TICKER"]}
            )
        }

        # Create a mock strategy environment.
        strategy = PointInTimeStrategy()
        strategy.p.portfolios = portfolios
        strategy.p.use_logging = False
        strategy.__init__()

        # Mock data feed (only AAPL).
        mock_data_aapl = MagicMock()
        mock_data_aapl._name = "AAPL"

        strategy.datas = [mock_data_aapl]
        strategy.timeline = mock_data_aapl
        strategy.timeline.datetime.date.return_value = datetime.date(2022, 1, 3)

        # Mock the getdatabyname method.
        def mock_getdatabyname(name):
            if name == "AAPL":
                return mock_data_aapl
            return None

        strategy.getdatabyname = mock_getdatabyname
        strategy.getposition = MagicMock(return_value=MagicMock(size=0))
        strategy.order_target_percent = MagicMock()

        # Execute the strategy logic.
        strategy.next()

        # Verify that the log records the missing stock.
        assert len(strategy.rebalance_log) == 1
        log_entry = strategy.rebalance_log[0]
        assert log_entry["model_tickers"] == 2
        assert log_entry["available_tickers"] == 1
        assert "MISSING_TICKER" in log_entry["missing_tickers_list"]

    def test_all_cash_period_handling(self):
        """Tests handling of all-cash periods (when data for all stocks is missing)."""
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame(
                {"Ticker": ["MISSING1", "MISSING2"]}
            )
        }

        strategy = PointInTimeStrategy()
        strategy.p.portfolios = portfolios
        strategy.p.use_logging = False
        strategy.__init__()

        # Mock a scenario with no matching data feeds.
        mock_timeline = MagicMock()
        mock_timeline.datetime.date.return_value = datetime.date(2022, 1, 3)
        mock_timeline._name = "TIMELINE"

        strategy.datas = [mock_timeline]
        strategy.timeline = mock_timeline
        strategy.getdatabyname = MagicMock(return_value=None)

        # Execute the strategy logic.
        strategy.next()

        # Verify that the strategy enters an all-cash period.
        assert len(strategy.rebalance_log) == 1
        log_entry = strategy.rebalance_log[0]
        assert log_entry["available_tickers"] == 0
        assert log_entry["model_tickers"] == 2

        # Verify that it moves to the next rebalance date.
        assert strategy.next_rebalance_idx == 1
        assert strategy.next_rebalance_date is None


class TestBuyAndHoldStrategy:
    """Tests the BuyAndHoldStrategy."""

    def test_single_purchase_logic(self):
        """Tests the single purchase logic."""
        strategy = BuyAndHoldStrategy()
        strategy.__init__()

        # Mock the order_target_percent method.
        strategy.order_target_percent = MagicMock()

        # Initial state.
        assert not strategy.bought

        # First call to next().
        strategy.next()
        assert strategy.bought
        strategy.order_target_percent.assert_called_once_with(target=0.99)

        # The second call to next() should not result in another purchase.
        strategy.order_target_percent.reset_mock()
        strategy.next()
        strategy.order_target_percent.assert_not_called()


class TestRunQuarterlyBacktest:
    """Tests for the run_quarterly_backtest function."""

    def create_test_data_feeds(self) -> dict:
        """Creates test data feeds."""
        dates = pd.date_range("2022-01-01", "2022-12-31", freq="D")

        data_feeds = {}
        for ticker in ["AAPL", "MSFT", "GOOGL"]:
            # Create mock price data (increasing over time).
            base_price = {"AAPL": 150, "MSFT": 300, "GOOGL": 2500}[ticker]
            prices = [base_price * (1 + 0.001 * i) for i in range(len(dates))]

            data = pd.DataFrame(
                {
                    "Open": prices,
                    "High": [p * 1.01 for p in prices],
                    "Low": [p * 0.99 for p in prices],
                    "Close": prices,
                    "Volume": [1000000] * len(dates),
                    "Dividend": [0.0] * len(dates),
                },
                index=dates,
            )

            data_feeds[ticker] = bt.feeds.PandasData(dataname=data, name=ticker)

        return data_feeds

    def test_successful_backtest_execution(self, mock_risk_free_service):
        """Tests successful backtest execution."""
        # Create a test portfolio.
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL", "MSFT"]}),
            datetime.date(2022, 7, 1): pd.DataFrame({"Ticker": ["GOOGL", "MSFT"]}),
        }

        data_feeds = self.create_test_data_feeds()
        initial_cash = 100000.0
        start_date = datetime.date(2022, 1, 1)
        end_date = datetime.date(2022, 12, 31)

        # Run the backtest.
        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=initial_cash,
            start_date=start_date,
            end_date=end_date,
            use_logging=False,
        )

        # Verify the return values.
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(metrics, dict)

        # Verify the portfolio value series is not empty.
        assert len(portfolio_value) > 0
        assert portfolio_value.iloc[0] == initial_cash  # Initial value.

        # Verify that the metrics dictionary contains the required fields.
        required_fields = [
            "start_date",
            "end_date",
            "initial_value",
            "final_value",
            "total_return",
            "annualized_return",
            "max_drawdown",
            "sharpe",
            "risk_free_series",
        ]
        for field in required_fields:
            assert field in metrics

        # Verify the reasonableness of the metric values.
        assert metrics["initial_value"] == initial_cash
        assert metrics["final_value"] > 0
        assert metrics["sharpe"] == 0.5
        assert metrics["risk_free_series"] == "DGS3MO"
        assert mock_risk_free_service.compute_sharpe.called
        assert metrics["start_date"] == start_date
        assert metrics["end_date"] == end_date

    def test_cash_initialization(self):
        """Tests cash initialization."""
        portfolios = {datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL"]})}

        data_feeds = self.create_test_data_feeds()
        initial_cash = 50000.0

        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=initial_cash,
            start_date=datetime.date(2022, 1, 1),
            end_date=datetime.date(2022, 6, 30),
            use_logging=False,
        )

        # Verify that the initial cash is set correctly.
        assert metrics["initial_value"] == initial_cash
        assert portfolio_value.iloc[0] == initial_cash

    def test_empty_portfolio_handling(self):
        """Tests the handling of an empty portfolio."""
        # Empty portfolio dictionary.
        portfolios = {}
        data_feeds = self.create_test_data_feeds()

        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=100000.0,
            start_date=datetime.date(2022, 1, 1),
            end_date=datetime.date(2022, 12, 31),
            use_logging=False,
        )

        # Should still return valid results (an all-cash strategy).
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(metrics, dict)
        assert len(portfolio_value) > 0

    def test_add_observers_parameter(self):
        """Tests the add_observers parameter."""
        portfolios = {datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL"]})}

        data_feeds = self.create_test_data_feeds()

        # Test adding observers.
        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=100000.0,
            start_date=datetime.date(2022, 1, 1),
            end_date=datetime.date(2022, 6, 30),
            use_logging=False,
            add_observers=True,
        )

        # Should execute normally.
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(metrics, dict)

    def test_add_annual_return_parameter(self):
        """Tests the add_annual_return analyzer parameter."""
        portfolios = {datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL"]})}

        data_feeds = self.create_test_data_feeds()

        # Test adding the annual return analyzer.
        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=100000.0,
            start_date=datetime.date(2022, 1, 1),
            end_date=datetime.date(2022, 12, 31),
            use_logging=False,
            add_annual_return=True,
        )

        # The metrics should include annual return data.
        assert "annual_returns" in metrics
        assert isinstance(metrics["annual_returns"], dict)


class TestRunBenchmarkBacktest:
    """Tests the run_benchmark_backtest function."""

    def create_spy_data(self) -> pd.DataFrame:
        """Creates test data for SPY."""
        dates = pd.date_range("2022-01-01", "2022-12-31", freq="D")
        base_price = 400.0
        prices = [base_price * (1 + 0.0005 * i) for i in range(len(dates))]

        return pd.DataFrame(
            {
                "Open": prices,
                "High": [p * 1.005 for p in prices],
                "Low": [p * 0.995 for p in prices],
                "Close": prices,
                "Volume": [50000000] * len(dates),
                "Dividend": [0.0] * len(dates),
            },
            index=dates,
        )

    def test_benchmark_backtest_execution(self, mock_risk_free_service):
        """Tests benchmark backtest execution."""
        spy_data = self.create_spy_data()
        initial_cash = 100000.0

        portfolio_value, metrics = run_benchmark_backtest(
            data=spy_data, initial_cash=initial_cash, ticker="SPY"
        )

        # Verify the return values.
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(metrics, dict)

        # Verify the portfolio value series.
        assert len(portfolio_value) > 0
        assert portfolio_value.iloc[0] == initial_cash

        # Verify the metrics.
        required_fields = [
            "start_date",
            "end_date",
            "initial_value",
            "final_value",
            "total_return",
            "annualized_return",
            "max_drawdown",
            "sharpe",
            "risk_free_series",
        ]
        for field in required_fields:
            assert field in metrics

        assert metrics["initial_value"] == initial_cash
        assert metrics["final_value"] > 0

    def test_custom_ticker(self, mock_risk_free_service):
        """Tests using a custom ticker."""
        data = self.create_spy_data()

        portfolio_value, metrics = run_benchmark_backtest(
            data=data, initial_cash=50000.0, ticker="QQQ"
        )

        # Should execute normally; the ticker parameter is mainly for display in logs.
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(metrics, dict)
        assert metrics["initial_value"] == 50000.0
        assert metrics["sharpe"] == 0.5
        assert metrics["risk_free_series"] == "DGS3MO"
        assert mock_risk_free_service.compute_sharpe.called


class TestGenerateReport:
    """Tests the generate_report function."""

    def create_test_metrics(self) -> dict:
        """Creates test metrics data."""
        return {
            "start_date": datetime.date(2022, 1, 1),
            "end_date": datetime.date(2022, 12, 31),
            "initial_value": 100000.0,
            "final_value": 120000.0,
            "total_return": 0.20,
            "annualized_return": 0.18,
            "max_drawdown": 5.5,
        }

    def create_test_portfolio_value(self) -> pd.Series:
        """Creates a test portfolio value series."""
        dates = pd.date_range("2022-01-01", "2022-12-31", freq="M")
        values = [100000 * (1 + 0.015 * i) for i in range(len(dates))]
        return pd.Series(values, index=dates)

    @patch("matplotlib.pyplot.show")
    @patch("matplotlib.pyplot.savefig")
    def test_basic_report_generation(self, mock_savefig, mock_show):
        """Tests basic report generation."""
        metrics = self.create_test_metrics()
        portfolio_value = self.create_test_portfolio_value()

        # Test basic report generation (without saving to a file).
        generate_report(
            metrics=metrics,
            title="Test Strategy Backtest",
            portfolio_value=portfolio_value,
        )

        # Verify that the plot show function was called.
        mock_show.assert_called_once()
        mock_savefig.assert_not_called()

    @patch("matplotlib.pyplot.show")
    @patch("matplotlib.pyplot.savefig")
    def test_report_with_file_output(self, mock_savefig, mock_show, tmp_path):
        """Tests report generation with file output."""
        metrics = self.create_test_metrics()
        portfolio_value = self.create_test_portfolio_value()
        output_path = tmp_path / "test_report.png"

        generate_report(
            metrics=metrics,
            title="Test Strategy with File Output",
            portfolio_value=portfolio_value,
            output_png=output_path,
        )

        # Verify that the savefig function was called.
        mock_savefig.assert_called_once_with(output_path, dpi=300, bbox_inches="tight")
        mock_show.assert_called_once()

    @patch("matplotlib.pyplot.show")
    @patch("matplotlib.pyplot.savefig")
    def test_report_with_benchmark(self, mock_savefig, mock_show):
        """Tests report generation with a benchmark."""
        metrics = self.create_test_metrics()
        portfolio_value = self.create_test_portfolio_value()

        # Create benchmark data.
        benchmark_value = (
            self.create_test_portfolio_value() * 0.9
        )  # Slightly lower benchmark performance.

        generate_report(
            metrics=metrics,
            title="Test Strategy vs Benchmark",
            portfolio_value=portfolio_value,
            benchmark_value=benchmark_value,
            benchmark_label="SPY Benchmark",
        )

        # Verify that the plot show function was called.
        mock_show.assert_called_once()


class TestEngineIntegration:
    """Integration tests for the backtest engine."""

    def test_end_to_end_backtest_flow(self, mock_risk_free_service):
        """Tests the end-to-end backtest workflow."""
        # 1. Prepare test data.
        portfolios = {
            datetime.date(2022, 1, 3): pd.DataFrame({"Ticker": ["AAPL", "MSFT"]}),
            datetime.date(2022, 7, 1): pd.DataFrame({"Ticker": ["GOOGL"]}),
        }

        # 2. Create data feeds.
        dates = pd.date_range("2022-01-01", "2022-12-31", freq="D")
        data_feeds = {}

        for ticker in ["AAPL", "MSFT", "GOOGL"]:
            base_price = {"AAPL": 150, "MSFT": 300, "GOOGL": 2500}[ticker]
            prices = [base_price * (1 + 0.001 * i) for i in range(len(dates))]

            data = pd.DataFrame(
                {
                    "Open": prices,
                    "High": [p * 1.01 for p in prices],
                    "Low": [p * 0.99 for p in prices],
                    "Close": prices,
                    "Volume": [1000000] * len(dates),
                    "Dividend": [0.0] * len(dates),
                },
                index=dates,
            )

            data_feeds[ticker] = bt.feeds.PandasData(dataname=data, name=ticker)

        # 3. Run the quarterly backtest.
        portfolio_value, metrics = run_quarterly_backtest(
            portfolios=portfolios,
            data_feeds=data_feeds,
            initial_cash=100000.0,
            start_date=datetime.date(2022, 1, 1),
            end_date=datetime.date(2022, 12, 31),
            use_logging=False,
        )

        # 4. Run the benchmark backtest.
        spy_data = pd.DataFrame(
            {
                "Open": [400] * len(dates),
                "High": [405] * len(dates),
                "Low": [395] * len(dates),
                "Close": [400 * (1 + 0.0005 * i) for i in range(len(dates))],
                "Volume": [50000000] * len(dates),
                "Dividend": [0.0] * len(dates),
            },
            index=dates,
        )

        benchmark_value, benchmark_metrics = run_benchmark_backtest(
            data=spy_data, initial_cash=100000.0, ticker="SPY"
        )

        # 5. Verify the results.
        assert isinstance(portfolio_value, pd.Series)
        assert isinstance(benchmark_value, pd.Series)
        assert len(portfolio_value) > 0
        assert len(benchmark_value) > 0

        # Verify the reasonableness of the metrics.
        assert metrics["final_value"] > 0
        assert benchmark_metrics["final_value"] > 0
        assert metrics["total_return"] != 0  # There should be a change in returns.
        assert benchmark_metrics["total_return"] != 0
        assert metrics["sharpe"] == 0.5
        assert benchmark_metrics["sharpe"] == 0.5
        assert metrics["risk_free_series"] == "DGS3MO"
        assert benchmark_metrics["risk_free_series"] == "DGS3MO"
        assert mock_risk_free_service.compute_sharpe.call_count >= 2

        # 6. Test report generation (without actually showing the plot).
        with patch("matplotlib.pyplot.show"):
            generate_report(
                metrics=metrics,
                title="Integration Test Strategy",
                portfolio_value=portfolio_value,
                benchmark_value=benchmark_value,
                benchmark_label="SPY",
            )
