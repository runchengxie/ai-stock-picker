import datetime

from ..engine import generate_report, run_benchmark_backtest
from ..prep import load_spy_data
from ....shared.config import get_backtest_period, get_initial_cash, get_report_settings
from ....shared.utils.paths import DB_PATH, OUTPUTS_DIR

# --- Backtest Configuration ---
SPY_TICKER = "SPY"


# Data loading functions and strategy classes have been moved to respective modules


def main(*, target_percent: float | None = None, log_level: int | None = None):
    """Main execution function - Run SPY benchmark backtest

    Args:
        target_percent: Optional target equity percent for buy-and-hold (e.g., 0.99)
        log_level: Optional logging level (e.g., logging.INFO/DEBUG)
    """
    print("--- SPY Benchmark Backtest ---")

    # Get unified time period from configuration file
    start_date, end_date = get_backtest_period()
    start_datetime = datetime.datetime.combine(start_date, datetime.time())
    end_datetime = datetime.datetime.combine(end_date, datetime.time())

    # Get initial cash from configuration file
    initial_cash = get_initial_cash("spy")

    print(f"Backtest period: {start_date} to {end_date}")
    print(f"Initial cash: ${initial_cash:,.2f}")

    try:
        # Load SPY data
        spy_data = load_spy_data(DB_PATH, start_datetime, end_datetime, SPY_TICKER)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Failed to load data: {e}")
        return

    # Run benchmark backtest
    portfolio_value, metrics = run_benchmark_backtest(
        data=spy_data,
        initial_cash=initial_cash,
        ticker=SPY_TICKER,
        target_percent=target_percent if target_percent is not None else 0.99,
        log_level=log_level,
    )

    # Generate report
    output_png = OUTPUTS_DIR / "spy_benchmark_returns.png"
    report_settings = get_report_settings()
    generate_report(
        metrics=metrics,
        title="SPY Benchmark Results (Total Return)",
        portfolio_value=portfolio_value,
        output_png=output_png,
        report_mode=report_settings.report_mode,
        with_underwater=report_settings.with_underwater,
        index_to_100=report_settings.index_to_100,
        use_log_scale=report_settings.use_log_scale,
        show_rolling=report_settings.show_rolling,
        rolling_window=report_settings.rolling_window,
        show_heatmap=report_settings.show_heatmap,
    )


if __name__ == "__main__":
    main()
