"""Backtesting engine module

Provides unified backtest runner, strategy classes and report generation functionality.
"""

import calendar
import datetime
from pathlib import Path
from typing import Any

import backtrader as bt
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import numpy as np
from backtrader.metabase import findowner

# ``backtrader`` strategies require a ``Cerebro`` instance during
# instantiation.  For unit tests where strategies are created in isolation this
# instance is absent, leading to attribute errors.  A lightweight metaclass is
# provided to safely handle this scenario by giving the strategy a dummy id when
# no ``Cerebro`` owner is found.
from backtrader.strategy import MetaStrategy

from ...shared.logging import StrategyLogger
from ...shared.services.marketdata import RiskFreeRateService, RiskFreeRateServiceError
from ...shared.utils.paths import OUTPUTS_DIR
from .prep import DividendPandasData


_RISK_FREE_SERVICE: RiskFreeRateService | None = None


def _get_risk_free_service() -> RiskFreeRateService:
    """Return a lazily-initialised risk-free rate service."""

    global _RISK_FREE_SERVICE
    if _RISK_FREE_SERVICE is None:
        _RISK_FREE_SERVICE = RiskFreeRateService.from_app_config()
    return _RISK_FREE_SERVICE


class _SafeMetaStrategy(MetaStrategy):
    """Metaclass that tolerates missing ``Cerebro`` when instantiating.

    When strategies are instantiated outside of a Backtrader ``Cerebro``
    environment (as the tests in this repository do), the original
    :class:`MetaStrategy` attempts to access ``cerebro._next_stid()`` and raises
    an ``AttributeError``.  This subclass assigns a dummy identifier instead of
    failing, allowing the strategy object to be constructed and its logic to be
    tested in isolation.
    """

    def donew(cls, *args, **kwargs):
        # Call ``MetaBase.donew`` directly to avoid the default ``MetaStrategy``
        # implementation which assumes the presence of a ``Cerebro`` instance.
        _obj, args, kwargs = super(MetaStrategy, cls).donew(*args, **kwargs)
        cerebro = findowner(_obj, bt.Cerebro)
        _obj.env = _obj.cerebro = cerebro
        _obj._id = cerebro._next_stid() if cerebro else 0
        return _obj, args, kwargs

    def dopreinit(cls, _obj, *args, **kwargs):
        # Skip heavy initialisation when running outside of Cerebro.  This
        # avoids dependencies on data feeds during unit tests.
        if getattr(_obj, "cerebro", None) is None:
            return _obj, args, kwargs
        return super().dopreinit(_obj, *args, **kwargs)

    def dopostinit(cls, _obj, *args, **kwargs):
        if getattr(_obj, "cerebro", None) is None:
            return _obj, args, kwargs
        return super().dopostinit(_obj, *args, **kwargs)


class PointInTimeStrategy(bt.Strategy, metaclass=_SafeMetaStrategy):
    """Unified point-in-time strategy class

    Integrates AI version and unfiltered version strategy logic,
    controlling differences through parameters.
    """

    params = (
        ("portfolios", None),
        ("use_logging", True),  # Control whether to use logging or print
        ("logger_name", "strategy"),
        ("log_level", None),
    )

    def __init__(self):
        """Initialise strategy state.

        ``PointInTimeStrategy`` is often instantiated in tests without passing
        the ``portfolios`` parameter and later re-initialised after the
        attribute has been populated.  The original implementation assumed that
        ``self.p.portfolios`` was always a dictionary, which caused an
        ``AttributeError`` when it was ``None``.  To make the strategy more
        robust and idempotent we gracefully handle a missing portfolio
        configuration by defaulting to an empty dictionary.
        """

        self.portfolios = self.p.portfolios or {}
        self.rebalance_dates = sorted(self.portfolios.keys())
        self.next_rebalance_idx = 0
        self.get_next_rebalance_date()
        # ``datas`` may be empty when instantiated outside of Cerebro
        self.timeline = self.datas[0] if getattr(self, "datas", []) else None
        self.rebalance_log = []

        # Initialize logger
        self.strategy_logger = StrategyLogger(
            use_logging=self.p.use_logging,
            logger_name=self.p.logger_name,
            level=self.p.log_level,
        )

    def log(self, txt, dt=None):
        """Log message"""
        if (
            dt is None
            and self.timeline is not None
            and hasattr(self.timeline, "datetime")
        ):
            try:
                dt = self.timeline.datetime.date(0)
            except Exception:
                dt = None
        self.strategy_logger.log(txt, dt)

    def get_next_rebalance_date(self):
        """Get next rebalancing date"""
        if self.next_rebalance_idx < len(self.rebalance_dates):
            self.next_rebalance_date = self.rebalance_dates[self.next_rebalance_idx]
        else:
            self.next_rebalance_date = None

    def next(self):
        """Main strategy logic"""
        current_date = self.timeline.datetime.date(0)

        # Process dividends for all held positions
        for data in self.datas:
            if hasattr(self, "broker") and hasattr(self, "getposition"):
                position = self.getposition(data)
            else:
                position = None
            if position is None or getattr(position, "size", 0) <= 0:
                continue
            dividend = getattr(data, "dividend", None)
            if dividend is None:
                continue
            dividend_value = dividend[0]
            if dividend_value > 0 and hasattr(self, "broker"):
                cash = position.size * dividend_value
                self.log(f"Dividend received for {data._name}: {cash:.2f}")
                self.broker.add_cash(cash)
                # Recommended default: accrue dividends as cash. Reinvestment
                # happens naturally during the next scheduled rebalancing for
                # this strategy (equal-weight allocation). Do not attempt to
                # maintain a global target percent here, because this strategy
                # has no such parameter and calling ``order_target_percent``
                # without a specific data target can raise errors.

        if self.next_rebalance_date and current_date >= self.next_rebalance_date:
            self.log(
                f"--- Rebalancing on {current_date} for signal date "
                f"{self.next_rebalance_date} ---"
            )

            target_tickers_df = self.p.portfolios[self.next_rebalance_date]
            target_tickers = set(target_tickers_df["Ticker"])

            self.log(
                "Diagnosis: Model selected "
                f"{len(target_tickers)} tickers: {target_tickers}"
            )

            available_data_tickers = {d._name for d in self.datas}

            final_target_tickers = target_tickers.intersection(available_data_tickers)
            missing_tickers = target_tickers - available_data_tickers

            self.log(
                "Diagnosis: "
                f"{len(available_data_tickers)} tickers have price data "
                "available in the database."
            )
            self.log(
                f"Diagnosis: Intersection has {len(final_target_tickers)} tickers: "
                f"{final_target_tickers if final_target_tickers else 'EMPTY'}"
            )

            # Record diagnostic information
            log_entry = {
                "rebalance_date": self.next_rebalance_date,
                "model_tickers": len(target_tickers),
                "available_tickers": len(final_target_tickers),
                "missing_tickers_list": ", ".join(missing_tickers),
            }
            self.rebalance_log.append(log_entry)

            if not final_target_tickers:
                self.log(
                    "CRITICAL WARNING: All-cash period. "
                    "No selected tickers were found in the price database."
                )
                if missing_tickers:
                    self.log(
                        "CRITICAL WARNING: The following "
                        f"{len(missing_tickers)} tickers were missing price data: "
                        f"{missing_tickers}"
                    )

                self.next_rebalance_idx += 1
                self.get_next_rebalance_date()
                return

            # Close positions not in target portfolio
            current_positions = {
                data._name for data in self.datas if self.getposition(data).size > 0
            }

            for ticker in current_positions:
                if ticker not in final_target_tickers:
                    data = self.getdatabyname(ticker)
                    self.log(f"Closing position in {ticker}")
                    self.order_target_percent(data=data, target=0.0)

            # Equal weight position building
            target_percent = 1.0 / len(final_target_tickers)
            for ticker in final_target_tickers:
                data = self.getdatabyname(ticker)
                self.log(
                    f"Setting target position for {ticker} to {target_percent:.2%}"
                )
                self.order_target_percent(data=data, target=target_percent)

            self.next_rebalance_idx += 1
            self.get_next_rebalance_date()
            self.log("--- Rebalancing Complete ---")

    def stop(self):
        """Processing when strategy ends"""
        self.log("--- Backtest Finished ---")
        log_df = pd.DataFrame(self.rebalance_log)
        if not log_df.empty:
            log_path = OUTPUTS_DIR / "rebalancing_diagnostics_log.csv"
            log_df.to_csv(log_path, index=False)
            self.log(f"Rebalancing diagnostics saved to: {log_path}")


class BuyAndHoldStrategy(bt.Strategy, metaclass=_SafeMetaStrategy):
    """Buy and hold strategy with dividend reinvestment into the same asset.

    - On the first bar, invest a target percentage of equity (default 99%).
    - On dividend days, book cash from dividends and maintain the target percent,
      which effectively reinvests dividends into the same asset.
    """

    params = (
        ("target_percent", 0.99),
        ("use_logging", True),
        ("logger_name", "benchmark"),
        ("log_level", None),
    )

    def __init__(self):
        self.bought = False
        # ``datas`` may be empty when instantiated outside of Cerebro (tests).
        self.timeline = self.datas[0] if getattr(self, "datas", []) else None
        self.strategy_logger = StrategyLogger(
            use_logging=self.p.use_logging,
            logger_name=self.p.logger_name,
            level=self.p.log_level,
        )

    def log(self, txt: str) -> None:
        dt = None
        if self.timeline is not None and hasattr(self.timeline, "datetime"):
            try:
                dt = self.timeline.datetime.date(0)
            except Exception:
                dt = None
        self.strategy_logger.log(txt, dt)

    def next(self):
        data = self.datas[0] if getattr(self, "datas", []) else None

        # Initial purchase
        if not self.bought:
            name = getattr(data, "_name", "asset") if data else "asset"
            self.log(f"Initial buy to target {self.p.target_percent:.2%} for {name}")
            self.order_target_percent(target=self.p.target_percent)
            self.bought = True
            return

        if data is None:
            return

        # Dividend handling: add cash, then keep target allocation to reinvest
        position = self.getposition(data) if hasattr(self, "getposition") else None
        if position is not None and getattr(position, "size", 0) > 0:
            dividend = getattr(data, "dividend", None)
            if dividend is not None:
                dividend_value = dividend[0]
                if dividend_value > 0 and hasattr(self, "broker"):
                    cash = position.size * dividend_value
                    self.log(f"Dividend received for {data._name}: {cash:.2f}")
                    self.broker.add_cash(cash)
                    # Maintain target percent to reinvest available cash
                    self.log(
                        "Reinvesting dividends to maintain target "
                        f"{self.p.target_percent:.2%}"
                    )
                    self.order_target_percent(target=self.p.target_percent)


def run_quarterly_backtest(
    portfolios: dict[datetime.date, pd.DataFrame],
    data_feeds: dict[str, bt.feeds.PandasData],
    initial_cash: float,
    start_date: datetime.date,
    end_date: datetime.date,
    use_logging: bool = True,
    add_observers: bool = False,
    add_annual_return: bool = False,
    log_level: int | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Run quarterly rebalancing backtest

    Args:
        portfolios: Portfolio dictionary
        data_feeds: Data feed dictionary
        initial_cash: Initial capital
        start_date: Start date
        end_date: End date
        use_logging: Whether to use logging (True) or print (False)
        add_observers: Whether to add observers
        add_annual_return: Whether to add annual return analyzer

    Returns:
        Tuple[pd.Series, Dict]: Portfolio value series and metrics dictionary
    """
    print(
        "\n--- Running Quarterly "
        f"{'AI Pick' if use_logging else 'Point-in-Time'} Strategy (Total Return) ---"
    )

    # Create Cerebro instance
    cerebro = bt.Cerebro(stdstats=not add_observers if add_observers else True)
    cerebro.broker.set_cash(initial_cash)

    # Add data feeds
    for name in sorted(data_feeds.keys()):
        cerebro.adddata(data_feeds[name], name=name)

    # Add strategy
    cerebro.addstrategy(
        PointInTimeStrategy,
        portfolios=portfolios,
        use_logging=use_logging,
        logger_name="strategy",
        log_level=log_level,
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    if add_annual_return:
        cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="annual_return")

    # Add observers (if needed)
    if add_observers:
        cerebro.addobserver(bt.observers.Broker)
        cerebro.addobserver(bt.observers.Trades)
        cerebro.addobserver(bt.observers.BuySell)

    # Run backtest
    results = cerebro.run()
    strat = results[0]

    # Extract metrics
    final_value = cerebro.broker.getvalue()
    total_return = strat.analyzers.returns.get_analysis().get("rtot", 0.0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().max.drawdown

    # Calculate annualized return
    duration_in_days = (end_date - start_date).days
    annualized_return = 0.0
    if duration_in_days > 0:
        duration_in_years = duration_in_days / 365.25
        if duration_in_years > 0:
            annualized_return = ((1 + total_return) ** (1 / duration_in_years)) - 1

    # Generate portfolio value series
    tr_analyzer = strat.analyzers.getbyname("time_return")
    returns = pd.Series(tr_analyzer.get_analysis())
    if not returns.empty:
        returns.index = pd.to_datetime(returns.index)
        returns = returns.sort_index()
    cumulative_returns = (1 + returns).cumprod()
    portfolio_value = initial_cash * cumulative_returns

    # Add initial value
    first_date = returns.index.min() if not returns.empty else start_date
    start_date_ts = pd.to_datetime(first_date) - pd.Timedelta(days=1)
    portfolio_value = pd.concat(
        [pd.Series({start_date_ts: initial_cash}), portfolio_value]
    )

    # Assemble metrics dictionary
    metrics = {
        "start_date": start_date,
        "end_date": end_date,
        "initial_value": initial_cash,
        "final_value": final_value,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
    }

    # Add annual return analysis (if available)
    if add_annual_return:
        annual_returns = strat.analyzers.getbyname("annual_return").get_analysis()
        metrics["annual_returns"] = annual_returns

    sharpe_ratio = None
    if not returns.empty:
        rf_service = _get_risk_free_service()
        idx = pd.DatetimeIndex(returns.index).tz_localize(None)
        start_idx = idx.min().date()
        end_idx = idx.max().date()
        try:
            rf_service.ensure_range(start_idx, end_idx)
            sharpe_ratio = rf_service.compute_sharpe(returns)
        except RiskFreeRateServiceError as exc:
            print(f"[WARN] Sharpe ratio skipped: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard
            print(f"[WARN] Sharpe ratio skipped due to unexpected error: {exc}")
        else:
            if sharpe_ratio is not None:
                metrics["sharpe"] = sharpe_ratio
                metrics["risk_free_series"] = rf_service.default_series

    return portfolio_value, metrics


def run_benchmark_backtest(
    data: pd.DataFrame,
    initial_cash: float,
    ticker: str = "SPY",
    *,
    target_percent: float = 0.99,
    log_level: int | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Run benchmark backtest (buy and hold)

    Args:
        data: Price data
        initial_cash: Initial capital
        ticker: Stock ticker

    Returns:
        Tuple[pd.Series, Dict]: Portfolio value series and metrics dictionary
    """
    print(f"\n--- Running {ticker} Buy-and-Hold Backtest (Total Return) ---")

    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(initial_cash)

    # Prepare data feed with dividend line support
    bt_feed = DividendPandasData(dataname=data, openinterest=None, name=ticker)
    cerebro.adddata(bt_feed)

    cerebro.addstrategy(
        BuyAndHoldStrategy,
        target_percent=target_percent,
        use_logging=True,
        logger_name="benchmark",
        log_level=log_level,
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    results = cerebro.run()
    strat = results[0]

    # Extract metrics
    final_value = cerebro.broker.getvalue()
    total_return = strat.analyzers.returns.get_analysis().get("rtot", 0.0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().max.drawdown

    start_date = data.index.min().date()
    end_date = data.index.max().date()

    # Calculate annualized return
    duration_in_days = (end_date - start_date).days
    annualized_return = 0.0
    if duration_in_days > 0:
        duration_in_years = duration_in_days / 365.25
        if duration_in_years > 0:
            annualized_return = ((1 + total_return) ** (1 / duration_in_years)) - 1

    # Generate portfolio value series
    tr_analyzer = strat.analyzers.getbyname("time_return")
    returns = pd.Series(tr_analyzer.get_analysis())
    if not returns.empty:
        returns.index = pd.to_datetime(returns.index)
        returns = returns.sort_index()
    cumulative_returns = (1 + returns).cumprod()
    portfolio_value = initial_cash * cumulative_returns
    start_date_ts = data.index.min() - pd.Timedelta(days=1)
    portfolio_value = pd.concat(
        [pd.Series({start_date_ts: initial_cash}), portfolio_value]
    )

    # Assemble metrics dictionary
    metrics = {
        "start_date": start_date,
        "end_date": end_date,
        "initial_value": initial_cash,
        "final_value": final_value,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
    }

    sharpe_ratio = None
    if not returns.empty:
        rf_service = _get_risk_free_service()
        idx = pd.DatetimeIndex(returns.index).tz_localize(None)
        start_idx = idx.min().date()
        end_idx = idx.max().date()
        try:
            rf_service.ensure_range(start_idx, end_idx)
            sharpe_ratio = rf_service.compute_sharpe(returns)
        except RiskFreeRateServiceError as exc:
            print(f"[WARN] Sharpe ratio skipped: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard
            print(f"[WARN] Sharpe ratio skipped due to unexpected error: {exc}")
        else:
            if sharpe_ratio is not None:
                metrics["sharpe"] = sharpe_ratio
                metrics["risk_free_series"] = rf_service.default_series

    return portfolio_value, metrics


def _index_to_100(series: pd.Series) -> pd.Series:
    """Rebase a time series to start at 100 while dropping missing values."""

    cleaned = series.dropna()
    if cleaned.empty:
        return cleaned
    return 100.0 * cleaned / cleaned.iloc[0]


def _underwater(series: pd.Series) -> pd.Series:
    """Compute drawdown series expressed as negative percentages."""

    cleaned = series.dropna()
    if cleaned.empty:
        return cleaned
    rolling_max = cleaned.cummax()
    return cleaned / rolling_max - 1.0


def generate_report(
    metrics: dict[str, Any],
    title: str,
    portfolio_value: pd.Series,
    output_png: Path | None = None,
    benchmark_value: pd.Series | None = None,
    benchmark_label: str = "Benchmark",
    benchmark_metrics: dict[str, Any] | None = None,
    *,
    report_mode: str = "both",
    with_underwater: bool = True,
    index_to_100: bool = True,
    use_log_scale: bool = False,
    show_rolling: bool = False,
    rolling_window: int = 252,
    show_heatmap: bool = False,
) -> None:
    """Generate unified backtest report

    Args:
        metrics: Metrics dictionary
        title: Report title
        portfolio_value: Portfolio value series
        output_png: Output image path (optional)
        benchmark_value: Benchmark value series (optional)
        benchmark_label: Benchmark label
        benchmark_metrics: Optional metrics dictionary for benchmark comparison
        report_mode: Controls textual output. Options are "comparison_only",
            "strategy_only", or "both".
        with_underwater: Include an underwater (drawdown) subplot when True.
        index_to_100: Rebase values to 100 before plotting when True.
        use_log_scale: Display the equity curve on a log scale when True.
    """

    valid_modes = {"comparison_only", "strategy_only", "both"}
    if report_mode not in valid_modes:  # pragma: no cover - defensive guard
        raise ValueError(
            "report_mode must be one of 'comparison_only', 'strategy_only', 'both'"
        )

    def _render_metrics_block(block_title: str, block_metrics: dict[str, Any]) -> None:
        print("\n" + "=" * 50)
        print(f"{block_title:^50}")
        print("=" * 50)
        print(
            "Time Period Covered:     "
            f"{block_metrics['start_date'].strftime('%Y-%m-%d')} "
            f"to {block_metrics['end_date'].strftime('%Y-%m-%d')}"
        )
        print(f"Initial Portfolio Value: ${block_metrics['initial_value']:,.2f}")
        print(f"Final Portfolio Value:   ${block_metrics['final_value']:,.2f}")
        print("-" * 50)
        print(f"Total Return:            {block_metrics['total_return'] * 100:.2f}%")
        print(
            f"Annualized Return:       {block_metrics['annualized_return'] * 100:.2f}%"
        )
        print(f"Max Drawdown:            {block_metrics['max_drawdown']:.2f}%")
        if block_metrics.get("sharpe") is not None:
            print(f"Sharpe Ratio:           {block_metrics['sharpe']:.3f}")
            rf_series = block_metrics.get("risk_free_series")
            if rf_series:
                print(f"Risk-free Series:       {rf_series}")
        print("=" * 50)

    def _format_percent(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value * 100:.2f}%"

    def _format_drawdown(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.2f}%"

    def _format_sharpe(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.3f}"

    if report_mode in {"strategy_only", "both"}:
        _render_metrics_block(title, metrics)

    benchmark_section_title = f"{benchmark_label} Benchmark Results"
    if benchmark_metrics is not None and report_mode == "both":
        _render_metrics_block(benchmark_section_title, benchmark_metrics)

    if benchmark_metrics is not None:
        strategy_label = title.replace("Results", "").strip() or "Strategy"
        benchmark_column_label = benchmark_label or "Benchmark"
        column_width = max(len(strategy_label), len(benchmark_column_label), 20)

        print("\nBenchmark Comparison (Unified Methodology):")
        header = (
            f"{'Metric':<20}{strategy_label:<{column_width}}"
            f"{benchmark_column_label:<{column_width}}"
        )
        print(header)
        print("-" * len(header))

        comparison_rows = [
            (
                "Total Return",
                _format_percent(metrics.get("total_return")),
                _format_percent(benchmark_metrics.get("total_return")),
            ),
            (
                "Annualized Return",
                _format_percent(metrics.get("annualized_return")),
                _format_percent(benchmark_metrics.get("annualized_return")),
            ),
            (
                "Max Drawdown",
                _format_drawdown(metrics.get("max_drawdown")),
                _format_drawdown(benchmark_metrics.get("max_drawdown")),
            ),
            (
                "Sharpe Ratio",
                _format_sharpe(metrics.get("sharpe")),
                _format_sharpe(benchmark_metrics.get("sharpe")),
            ),
        ]

        for metric_name, strategy_value, benchmark_value_str in comparison_rows:
            print(
                f"{metric_name:<20}{strategy_value:<{column_width}}"
                f"{benchmark_value_str:<{column_width}}"
            )

        print("-" * len(header))
        strategy_period = (
            f"{metrics['start_date'].strftime('%Y-%m-%d')}"
            f" to {metrics['end_date'].strftime('%Y-%m-%d')}"
        )
        benchmark_period = (
            f"{benchmark_metrics['start_date'].strftime('%Y-%m-%d')}"
            f" to {benchmark_metrics['end_date'].strftime('%Y-%m-%d')}"
        )
        print(f"Period Covered:{strategy_period:>18} | {benchmark_period}")
        print(
            "Initial / Final:"  # Align initial and final values for both series
            f" ${metrics['initial_value']:,.2f} → ${metrics['final_value']:,.2f}"
            f" | ${benchmark_metrics['initial_value']:,.2f}"
            f" → ${benchmark_metrics['final_value']:,.2f}"
        )
        rf_series = metrics.get("risk_free_series") or benchmark_metrics.get(
            "risk_free_series"
        )
        if rf_series:
            print(f"Risk-free Series: {rf_series}")

    # Harmonise data prior to plotting
    portfolio_series = portfolio_value.sort_index()
    benchmark_series = (
        benchmark_value.sort_index() if benchmark_value is not None else None
    )

    if benchmark_series is not None:
        aligned = pd.concat(
            [
                portfolio_series.rename("Strategy"),
                benchmark_series.rename(benchmark_label or "Benchmark"),
            ],
            axis=1,
        ).sort_index()
        aligned = aligned.ffill().dropna()
        if aligned.empty:
            benchmark_series = None
        else:
            portfolio_series = aligned.iloc[:, 0]
            benchmark_series = aligned.iloc[:, 1]

    portfolio_returns = portfolio_series.pct_change().dropna()
    benchmark_returns = (
        benchmark_series.pct_change().dropna() if benchmark_series is not None else None
    )

    risk_free_daily: pd.Series | None = None
    if not portfolio_returns.empty:
        idx = pd.DatetimeIndex(portfolio_returns.index).tz_localize(None)
        start_idx = idx.min().date()
        end_idx = idx.max().date()
        try:
            rf_service = _get_risk_free_service()
            rf_service.ensure_range(start_idx, end_idx)
            risk_free_daily = rf_service.get_series_for_index(idx)
        except RiskFreeRateServiceError as exc:
            print(f"[WARN] Rolling statistics skipped: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard
            print(
                "[WARN] Rolling statistics skipped due to unexpected error: "
                f"{exc}"
            )

    if index_to_100:
        portfolio_plot = _index_to_100(portfolio_series)
        benchmark_plot = (
            _index_to_100(benchmark_series) if benchmark_series is not None else None
        )
        y_label = "Index (Base = 100)"
    else:
        portfolio_plot = portfolio_series
        benchmark_plot = benchmark_series
        y_label = "Portfolio Value ($)"

    # Generate chart
    print("\nGenerating plot...")
    plt.style.use("seaborn-v0_8-whitegrid")
    nrows = 2 if with_underwater else 1
    height_ratios = [0.45, 3, 1] if with_underwater else [0.45, 3]
    figures_to_save: list[tuple[Any, Path]] = []
    fig = plt.figure(figsize=(14, 8))
    grid_spec = fig.add_gridspec(len(height_ratios), 1, height_ratios=height_ratios)

    ax_header = fig.add_subplot(grid_spec[0, 0])
    ax_header.axis("off")

    ax_equity = fig.add_subplot(grid_spec[1, 0])
    if with_underwater:
        ax_drawdown = fig.add_subplot(grid_spec[2, 0], sharex=ax_equity)

    portfolio_label = title.split("(")[0].strip() or "Strategy"
    portfolio_plot.plot(ax=ax_equity, label=portfolio_label, lw=2, color="steelblue")

    if benchmark_plot is not None:
        benchmark_plot.plot(
            ax=ax_equity, label=benchmark_label or "Benchmark", lw=2, color="darkorange"
        )

    legend_columns = 2 if benchmark_plot is not None else 1
    ax_equity.set_ylabel(y_label, fontsize=12)
    ax_equity.legend(
        loc="upper left",
        bbox_to_anchor=(0, -0.12),
        ncol=legend_columns,
        frameon=False,
        fontsize=11,
    )
    if not index_to_100:
        ax_equity.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda value, _: f"${value:,.0f}")
        )
    if use_log_scale:
        ax_equity.set_yscale("log")

    def _build_metrics_block(
        block_metrics: dict[str, Any],
        *,
        title_prefix: str,
    ) -> str:
        lines: list[str] = [title_prefix] if title_prefix else []
        total_return = block_metrics.get("total_return")
        if total_return is not None:
            lines.append(f"TotRet: {total_return * 100:.2f}%")
        annualized = block_metrics.get("annualized_return")
        if annualized is not None:
            lines.append(f"CAGR: {annualized * 100:.2f}%")
        max_dd = block_metrics.get("max_drawdown")
        if max_dd is not None:
            lines.append(f"MaxDD: {max_dd:.2f}%")
        sharpe_val = block_metrics.get("sharpe")
        if sharpe_val is not None:
            lines.append(f"Sharpe: {sharpe_val:.2f}")
        return "\n".join(lines)

    header_box = dict(
        boxstyle="round,pad=0.3",
        facecolor="white",
        edgecolor="#333333",
        alpha=0.9,
    )
    header_kwargs = dict(
        fontfamily="monospace",
        fontsize=10,
        transform=ax_header.transAxes,
        bbox=header_box,
    )

    left_header = _build_metrics_block(metrics, title_prefix=portfolio_label)
    if left_header:
        ax_header.text(
            0.01,
            0.95,
            left_header,
            ha="left",
            va="top",
            **header_kwargs,
        )

    if benchmark_metrics is not None:
        right_header = _build_metrics_block(
            benchmark_metrics,
            title_prefix=benchmark_label or "Benchmark",
        )
        if right_header:
            ax_header.text(
                0.99,
                0.95,
                right_header,
                ha="right",
                va="top",
                **header_kwargs,
            )

    fig.suptitle(title, y=0.995, fontsize=16)

    if with_underwater:
        drawdown_series = _underwater(portfolio_series)
        if not drawdown_series.empty:
            ax_drawdown.plot(
                drawdown_series.index,
                drawdown_series,
                lw=1.2,
                color="steelblue",
                label=f"{portfolio_label} Drawdown",
            )
            ax_drawdown.fill_between(
                drawdown_series.index,
                drawdown_series,
                0,
                color="steelblue",
                alpha=0.25,
                step="pre",
            )
        if benchmark_series is not None:
            benchmark_drawdown = _underwater(benchmark_series)
            if not benchmark_drawdown.empty:
                ax_drawdown.plot(
                    benchmark_drawdown.index,
                    benchmark_drawdown,
                    lw=1.0,
                    color="darkorange",
                    alpha=0.8,
                    label=f"{benchmark_label or 'Benchmark'} Drawdown",
                )
        handles, _ = ax_drawdown.get_legend_handles_labels()
        if handles:
            ax_drawdown.legend(loc="lower left", fontsize=9)
        ax_drawdown.set_ylabel("Drawdown", fontsize=12)
        ax_drawdown.set_xlabel("Date", fontsize=12)
        ax_drawdown.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
        ax_drawdown.grid(True, alpha=0.3)
    else:
        ax_equity.set_xlabel("Date", fontsize=12)

    ax_equity.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    if output_png:
        figures_to_save.append((fig, output_png))

    def _annualized_volatility(series: pd.Series) -> float | None:
        if series.empty:
            return None
        std = series.std(ddof=1)
        if std is None or np.isnan(std):
            return None
        return float(std * np.sqrt(252))

    def _compute_period_stats(
        value_series: pd.Series,
        returns_series: pd.Series,
        years: int,
        *,
        rf_series: pd.Series | None = None,
        benchmark_values: pd.Series | None = None,
        benchmark_returns: pd.Series | None = None,
    ) -> dict[str, float | None]:
        if value_series.empty or len(value_series) < 2:
            return {}
        end = value_series.index.max()
        start = end - pd.DateOffset(years=years)
        period_values = value_series[value_series.index >= start]
        if len(period_values) < 2:
            return {}
        period_returns = returns_series[returns_series.index >= period_values.index[0]]
        if period_returns.empty:
            return {}

        start_val = float(period_values.iloc[0])
        end_val = float(period_values.iloc[-1])
        if start_val <= 0 or end_val <= 0:
            return {}
        duration_days = (period_values.index[-1] - period_values.index[0]).days
        if duration_days <= 0:
            return {}
        duration_years = duration_days / 365.25
        cagr = (end_val / start_val) ** (1 / duration_years) - 1
        dd_series = _underwater(period_values)
        max_dd = float(dd_series.min()) if not dd_series.empty else None
        calmar = None
        if max_dd is not None and max_dd != 0:
            calmar = cagr / abs(max_dd)

        aligned_rf = None
        if rf_series is not None and not rf_series.empty:
            aligned_rf = rf_series.reindex(period_returns.index).ffill().bfill()
        excess_returns = (
            period_returns - aligned_rf if aligned_rf is not None else period_returns
        )
        mean_excess = excess_returns.mean()
        downside = excess_returns[excess_returns < 0]
        downside_std = (
            float(np.sqrt((downside.pow(2).mean()))) if not downside.empty else None
        )
        sortino = None
        if downside_std and downside_std > 0:
            sortino = float(mean_excess / downside_std * np.sqrt(252))

        bench_stats = {}
        if benchmark_values is not None and benchmark_returns is not None:
            bench_values = benchmark_values[
                benchmark_values.index >= period_values.index[0]
            ]
            bench_returns_slice = benchmark_returns[
                benchmark_returns.index >= period_returns.index[0]
            ]
            if not bench_values.empty and len(bench_values) >= 2:
                rel = period_returns.reindex(bench_returns_slice.index).dropna()
                bench_aligned = bench_returns_slice.reindex(rel.index).dropna()
                rel = rel.reindex(bench_aligned.index)
                diff = rel - bench_aligned
                if not diff.empty:
                    diff_std = diff.std(ddof=1)
                    if (
                        diff_std is not None
                        and not np.isnan(diff_std)
                        and diff_std != 0
                    ):
                        info_ratio = float(diff.mean() / diff_std * np.sqrt(252))
                    else:
                        info_ratio = None
                    if diff_std is not None and not np.isnan(diff_std):
                        tracking_error = float(diff_std * np.sqrt(252))
                    else:
                        tracking_error = None
                else:
                    info_ratio = None
                    tracking_error = None
            else:
                info_ratio = None
                tracking_error = None
            bench_stats = {
                "info_ratio": info_ratio,
                "tracking_error": tracking_error,
            }
        period_vol = _annualized_volatility(period_returns)
        stats: dict[str, float | None] = {
            "cagr": float(cagr),
            "max_drawdown": max_dd,
            "calmar": calmar,
            "sortino": sortino,
            "volatility": period_vol,
        }
        stats.update(bench_stats)
        return stats

    period_horizons = [1, 3, 5]
    period_rows: list[tuple[str, dict[str, float | None]]] = []
    for horizon in period_horizons:
        stats = _compute_period_stats(
            portfolio_series,
            portfolio_returns,
            horizon,
            rf_series=risk_free_daily,
            benchmark_values=benchmark_series,
            benchmark_returns=benchmark_returns,
        )
        if stats:
            period_rows.append((f"Last {horizon}Y", stats))

    if period_rows:
        print("\nSegmented Performance (ending on latest observation):")
        header_parts = [
            f"{'Horizon':<12}",
            f"{'CAGR':>10}",
            f"{'MaxDD':>10}",
            f"{'Calmar':>10}",
            f"{'Sortino':>10}",
            f"{'Vol':>10}",
        ]
        has_benchmark_stats = benchmark_series is not None and any(
            row[1].get("info_ratio") is not None
            or row[1].get("tracking_error") is not None
            for row in period_rows
        )
        if has_benchmark_stats:
            header_parts.extend([f"{'InfoR':>10}", f"{'TrackErr':>10}"])
        header = "".join(header_parts)
        print(header)
        print("-" * len(header))

        def _fmt(value: float | None, *, pct: bool = False) -> str:
            if value is None or np.isnan(value):
                return "N/A".rjust(10)
            if pct:
                return f"{value * 100:>9.2f}%"
            return f"{value:>10.2f}"

        for label, stats in period_rows:
            row = [f"{label:<12}"]
            row.append(_fmt(stats.get("cagr"), pct=True))
            max_dd_val = stats.get("max_drawdown")
            if max_dd_val is None or np.isnan(max_dd_val):
                row.append("N/A".rjust(10))
            else:
                row.append(f"{max_dd_val * 100:>9.2f}%")
            row.append(_fmt(stats.get("calmar")))
            row.append(_fmt(stats.get("sortino")))
            row.append(_fmt(stats.get("volatility"), pct=True))
            if has_benchmark_stats:
                row.append(_fmt(stats.get("info_ratio")))
                row.append(_fmt(stats.get("tracking_error"), pct=True))
            print("".join(row))

    if show_rolling and not portfolio_returns.empty:
        window = max(int(rolling_window), 2)
        aligned_rf = (
            risk_free_daily.reindex(portfolio_returns.index).ffill().bfill()
            if risk_free_daily is not None
            else pd.Series(0.0, index=portfolio_returns.index)
        )
        excess_returns = portfolio_returns - aligned_rf
        rolling_vol = portfolio_returns.rolling(window).std(ddof=1) * np.sqrt(252)
        rolling_mean = excess_returns.rolling(window).mean()
        rolling_std = excess_returns.rolling(window).std(ddof=1).replace(0, np.nan)
        rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(252)
        rolling_fig, ax_roll = plt.subplots(figsize=(14, 4))
        ax_roll.plot(
            rolling_vol.index,
            rolling_vol,
            color="steelblue",
            label="Rolling Volatility",
        )
        ax_roll.set_ylabel("Volatility", color="steelblue")
        ax_roll.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
        ax_roll.tick_params(axis="y", labelcolor="steelblue")

        ax_sharpe = ax_roll.twinx()
        ax_sharpe.plot(
            rolling_sharpe.index,
            rolling_sharpe,
            color="darkorange",
            label="Rolling Sharpe",
        )
        ax_sharpe.set_ylabel("Sharpe", color="darkorange")
        ax_sharpe.tick_params(axis="y", labelcolor="darkorange")
        ax_roll.set_title(f"{portfolio_label} {window}-Day Rolling Metrics")
        ax_roll.set_xlabel("Date")
        ax_roll.grid(True, alpha=0.3)
        lines, labels = ax_roll.get_legend_handles_labels()
        lines2, labels2 = ax_sharpe.get_legend_handles_labels()
        ax_roll.legend(lines + lines2, labels + labels2, loc="upper left")
        rolling_fig.tight_layout()
        if output_png:
            rolling_path = output_png.with_name(
                f"{output_png.stem}_rolling{output_png.suffix}"
            )
            figures_to_save.append((rolling_fig, rolling_path))

    if show_heatmap and not portfolio_returns.empty:
        monthly_returns = (1 + portfolio_returns).resample("ME").prod() - 1
        if not monthly_returns.empty:
            monthly_df = monthly_returns.to_frame(name="return")
            monthly_df["Year"] = monthly_df.index.year
            monthly_df["Month"] = monthly_df.index.month
            annual_returns = monthly_df.groupby("Year")["return"].apply(
                lambda x: (1 + x).prod() - 1
            )
            pivot = monthly_df.pivot(index="Year", columns="Month", values="return")
            pivot = pivot.sort_index()
            pivot_columns = list(range(1, 13))
            pivot = pivot.reindex(columns=pivot_columns)
            month_labels = [calendar.month_abbr[m] for m in pivot_columns]
            heatmap_data = pivot.values
            annual_col = annual_returns.reindex(pivot.index)

            fig_heatmap, ax_heatmap = plt.subplots(figsize=(14, 6))
            im = ax_heatmap.imshow(
                heatmap_data,
                aspect="auto",
                cmap="RdYlGn",
                vmin=-0.3,
                vmax=0.3,
            )
            ax_heatmap.set_xticks(range(len(month_labels)))
            ax_heatmap.set_xticklabels(month_labels)
            ax_heatmap.set_yticks(range(len(pivot.index)))
            ax_heatmap.set_yticklabels(pivot.index)
            ax_heatmap.set_title(f"{portfolio_label} Monthly Returns Heatmap")
            cbar = fig_heatmap.colorbar(im, ax=ax_heatmap, pad=0.01)
            cbar.ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))

            for i, year in enumerate(pivot.index):
                for j, month in enumerate(pivot_columns):
                    value = heatmap_data[i, j]
                    if np.isnan(value):
                        continue
                    ax_heatmap.text(
                        j,
                        i,
                        f"{value * 100:.1f}%",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="black" if abs(value) < 0.15 else "white",
                    )

            ax_heatmap.set_xlabel("Month")
            ax_heatmap.set_ylabel("Year")

            if not annual_col.empty:
                ax_annual = ax_heatmap.twinx()
                ax_annual.set_ylim(ax_heatmap.get_ylim())
                ax_annual.set_yticks(ax_heatmap.get_yticks())
                ax_annual.set_yticklabels(
                    [
                        f"{val * 100:.1f}%" if not pd.isna(val) else "N/A"
                        for val in annual_col
                    ]
                )
                ax_annual.set_ylabel("Annual Return")
            fig_heatmap.tight_layout()
            if output_png:
                heatmap_path = output_png.with_name(
                    f"{output_png.stem}_heatmap{output_png.suffix}"
                )
                figures_to_save.append((fig_heatmap, heatmap_path))

    for fig_obj, path in figures_to_save:
        # Route saves through pyplot so existing tests and callers that patch
        # ``matplotlib.pyplot.savefig`` continue to observe file writes.
        plt.figure(fig_obj.number)
        plt.savefig(path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {path}")

    plt.show()
