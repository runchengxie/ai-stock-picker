import datetime as dt

import pandas as pd

from stock_analysis.research.backtest.strategies.pe_sector_alpha import (
    PeSectorAlphaSettings,
    _build_benchmark_series,
    _build_portfolios,
    _compute_daily_alpha_panel,
    _compute_metrics,
    _select_rebalance_dates,
    _simulate_dollar_neutral_portfolio,
    _simulate_equal_weight_portfolio,
    calculate_alpha_reference,
)


def test_select_rebalance_dates_monthly_uses_last_available_day():
    idx = pd.to_datetime(
        ["2024-01-02", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-28"]
    )

    result = _select_rebalance_dates(pd.DatetimeIndex(idx), "monthly")

    expected = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-28"])
    assert list(result) == list(expected)


def test_build_portfolios_respects_market_cap_universe():
    settings = PeSectorAlphaSettings(universe_size=2, holdings=1, short_holdings=1)
    alpha = pd.DataFrame(
        {
            "AAA": [0.1],
            "BBB": [0.8],
            "CCC": [0.6],
        },
        index=pd.to_datetime(["2024-01-31"]),
    )
    market_cap = pd.DataFrame(
        {
            "AAA": [300.0],
            "BBB": [100.0],
            "CCC": [200.0],
        },
        index=alpha.index,
    )
    sector = pd.Series({"AAA": "Tech", "BBB": "Tech", "CCC": "Health"})

    portfolios, long_short_portfolios, combined, long_short_combined = (
        _build_portfolios(alpha, market_cap, sector, settings)
    )

    assert list(portfolios[dt.date(2024, 1, 31)]["Ticker"]) == ["CCC"]
    assert list(combined["Ticker"]) == ["CCC"]
    assert list(long_short_portfolios[dt.date(2024, 1, 31)]["Ticker"]) == ["CCC", "AAA"]
    assert set(long_short_combined["Side"]) == {"LONG", "SHORT"}


def test_simulate_equal_weight_portfolio_rolls_capital_forward():
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 18.0, 18.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    portfolios = {
        dt.date(2024, 1, 1): pd.DataFrame({"Ticker": ["AAA", "BBB"]}),
    }

    values, diagnostics = _simulate_equal_weight_portfolio(prices, portfolios, 100.0)

    assert diagnostics.iloc[0]["tradable_count"] == 2
    assert round(values.iloc[-1], 4) == 104.5455


def test_build_benchmark_series_uses_start_date_cutoff():
    prices = pd.DataFrame(
        {"SPY": [100.0, 102.0, 101.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )

    series = _build_benchmark_series(
        prices,
        ticker="SPY",
        initial_cash=100.0,
        start_date=pd.Timestamp("2024-01-02"),
    )

    assert round(series.iloc[-1], 4) == 99.0196


def test_simulate_dollar_neutral_portfolio_offsets_long_and_short():
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 18.0, 16.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    portfolios = {
        dt.date(2024, 1, 1): pd.DataFrame(
            {
                "Ticker": ["AAA", "BBB"],
                "Side": ["LONG", "SHORT"],
            }
        ),
    }

    values, diagnostics = _simulate_dollar_neutral_portfolio(prices, portfolios, 100.0)

    assert diagnostics.iloc[0]["tradable_longs"] == 1
    assert diagnostics.iloc[0]["tradable_shorts"] == 1
    assert round(values.iloc[-1], 4) == 110.7823


def test_compute_metrics_returns_expected_totals():
    series = pd.Series(
        [100.0, 105.0, 110.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )

    metrics = _compute_metrics(series, 100.0)

    assert metrics["final_value"] == 110.0
    assert round(metrics["total_return"], 6) == 0.1


def test_reference_alpha_matches_panel_implementation_on_sample():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    records = []
    for i, date in enumerate(dates):
        records.extend(
            [
                (date, "AAA", 10.0 + i * 0.1, "Tech"),
                (date, "BBB", 20.0 - i * 0.05, "Tech"),
                (date, "CCC", 15.0 + ((-1) ** i) * 0.2, "Health"),
            ]
        )
    df = pd.DataFrame(records, columns=["date", "instrument", "pe", "sector_data"])
    df = df.set_index(["date", "instrument"]).sort_index()

    reference = calculate_alpha_reference(
        df,
        backfill_limit=252,
        winsor_std=3.0,
        z_window=20,
        min_periods=5,
    )
    pe_panel = df["pe"].unstack("instrument")
    sector_map = (
        df.reset_index()
        .drop_duplicates(subset=["instrument"], keep="last")
        .set_index("instrument")["sector_data"]
    )
    settings = PeSectorAlphaSettings(z_window=20, min_periods=5)
    panel_alpha = _compute_daily_alpha_panel(pe_panel, sector_map, settings)
    panel_series = panel_alpha.stack(future_stack=True).rename_axis(
        ["date", "instrument"]
    )

    aligned = pd.concat(
        [reference.rename("reference"), panel_series.rename("panel")], axis=1
    ).dropna()

    assert not aligned.empty
    pd.testing.assert_series_equal(
        aligned["reference"].round(6),
        aligned["panel"].round(6),
        check_dtype=False,
        check_names=False,
    )
