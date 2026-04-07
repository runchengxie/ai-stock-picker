"""PE-based sector-neutral alpha backtest.

This strategy reads the local SimFin zip files directly and runs a
research-grade long-only backtest:

1. Forward-fill PE by ticker with a 252-day cap.
2. Winsorize the cross-section by date at +/- 3 standard deviations.
3. Compute a 240-day time-series z-score by ticker and flip the sign.
4. Sector-neutralize the rebalance-date alpha cross-section.
5. Select the top-ranked names inside a large-cap universe and run an
   equal-weight rebalanced portfolio backtest using adjusted close prices.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ....shared.config import get_initial_cash
from ....shared.utils.paths import DATA_DIR, OUTPUTS_DIR
from ..engine import generate_report

PE_COLUMN_MAP = {
    "quarterly": "Price to Earnings Ratio (quarterly)",
    "ttm": "Price to Earnings Ratio (ttm)",
    "adjusted": "Price to Earnings Ratio (Adjusted)",
}

OUTPUT_DIR = OUTPUTS_DIR / "pe_sector_alpha"
PORTFOLIO_DIR = OUTPUT_DIR / "portfolios"
LONG_SHORT_PORTFOLIO_DIR = OUTPUT_DIR / "long_short_portfolios"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class PeSectorAlphaSettings:
    """Runtime settings for the PE alpha backtest."""

    derived_zip: Path = DATA_DIR / "us-derived-shareprices-daily.zip"
    prices_zip: Path = DATA_DIR / "us-shareprices-daily.zip"
    companies_zip: Path = DATA_DIR / "us-companies.zip"
    industries_zip: Path = DATA_DIR / "industries.zip"
    pe_field: str = "quarterly"
    rebalance_frequency: str = "monthly"
    universe_size: int = 3000
    holdings: int = 30
    short_holdings: int = 30
    backfill_limit: int = 252
    winsor_std: float = 3.0
    z_window: int = 240
    min_periods: int = 30
    initial_cash: float = field(default_factory=lambda: get_initial_cash("quant"))

    @property
    def pe_column(self) -> str:
        try:
            return PE_COLUMN_MAP[self.pe_field]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unsupported PE field: {self.pe_field}") from exc

    @classmethod
    def from_env(cls) -> PeSectorAlphaSettings:
        base = cls()
        return cls(
            pe_field=_env_str("PE_ALPHA_PE_FIELD", base.pe_field),
            rebalance_frequency=_env_str(
                "PE_ALPHA_REBALANCE_FREQUENCY", base.rebalance_frequency
            ),
            universe_size=_env_int("PE_ALPHA_UNIVERSE_SIZE", base.universe_size),
            holdings=_env_int("PE_ALPHA_HOLDINGS", base.holdings),
            short_holdings=_env_int("PE_ALPHA_SHORT_HOLDINGS", base.short_holdings),
            backfill_limit=_env_int("PE_ALPHA_BACKFILL_LIMIT", base.backfill_limit),
            winsor_std=_env_float("PE_ALPHA_WINSOR_STD", base.winsor_std),
            z_window=_env_int("PE_ALPHA_Z_WINDOW", base.z_window),
            min_periods=_env_int("PE_ALPHA_MIN_PERIODS", base.min_periods),
            initial_cash=_env_float("PE_ALPHA_INITIAL_CASH", base.initial_cash),
        )


def _normalize_tickers(col: pd.Series) -> pd.Series:
    return col.astype("string").str.upper().str.strip().replace({"": pd.NA})


def calculate_alpha_reference(
    df: pd.DataFrame,
    *,
    backfill_limit: int = 252,
    winsor_std: float = 3.0,
    z_window: int = 240,
    min_periods: int = 30,
) -> pd.Series:
    """Reference implementation mirroring the user's alpha formula.

    The input must be a MultiIndex DataFrame indexed by ``[date, instrument]``
    and include ``pe`` plus ``sector_data`` columns.
    """

    required_columns = {"pe", "sector_data"}
    if not required_columns.issubset(df.columns):
        missing = required_columns.difference(df.columns)
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if not isinstance(df.index, pd.MultiIndex) or list(df.index.names) != [
        "date",
        "instrument",
    ]:
        raise ValueError("Index must be a MultiIndex named ['date', 'instrument']")

    val = df["pe"].groupby(level="instrument").ffill(limit=backfill_limit)

    def winsorize_series(series: pd.Series) -> pd.Series:
        mean = series.mean()
        std = series.std()
        return series.clip(
            lower=mean - winsor_std * std,
            upper=mean + winsor_std * std,
        )

    val = val.groupby(level="date", group_keys=False).apply(winsorize_series)

    def get_ts_zscore(series: pd.Series) -> pd.Series:
        roll = series.rolling(window=z_window, min_periods=min_periods)
        return -((series - roll.mean()) / roll.std())

    val = val.groupby(level="instrument", group_keys=False).apply(get_ts_zscore)

    sector = df["sector_data"].groupby(level="instrument").ffill()
    temp_df = pd.DataFrame({"alpha": val, "sector": sector}, index=df.index)

    final_alpha = temp_df.groupby(
        [temp_df.index.get_level_values("date"), temp_df["sector"]]
    )["alpha"].transform(lambda group: group - group.mean())

    final_alpha.index = df.index
    final_alpha.name = "alpha"
    return final_alpha


def _select_rebalance_dates(
    index: pd.DatetimeIndex, frequency: str
) -> pd.DatetimeIndex:
    freq_map = {"monthly": "M", "quarterly": "Q"}
    try:
        period_code = freq_map[frequency]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported rebalance frequency: {frequency}") from exc

    dates = pd.Series(index, index=index)
    grouped = dates.groupby(index.to_period(period_code))
    return pd.DatetimeIndex(grouped.tail(1).index)


def _load_sector_map(settings: PeSectorAlphaSettings) -> pd.Series:
    companies = pd.read_csv(
        settings.companies_zip,
        sep=";",
        usecols=["Ticker", "IndustryId"],
        dtype={"Ticker": "string"},
    )
    industries = pd.read_csv(
        settings.industries_zip,
        sep=";",
        usecols=["IndustryId", "Sector"],
    )

    companies["Ticker"] = _normalize_tickers(companies["Ticker"])
    companies = companies.dropna(subset=["Ticker"])

    merged = companies.merge(industries, on="IndustryId", how="left")
    merged["has_sector"] = merged["Sector"].notna()
    merged = merged.sort_values(["Ticker", "has_sector"])
    merged = merged.drop_duplicates(subset=["Ticker"], keep="last")

    sector_map = merged.set_index("Ticker")["Sector"].dropna()
    return sector_map.astype("string")


def _load_signal_panels(
    settings: PeSectorAlphaSettings, sector_map: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame]:
    print(
        "Loading signal inputs from "
        f"{settings.derived_zip.name} using {settings.pe_column}..."
    )

    usecols = ["Ticker", "Date", settings.pe_column, "Market-Cap"]
    valid_tickers = set(sector_map.index.tolist())
    pieces: list[pd.DataFrame] = []
    total_rows = 0

    reader = pd.read_csv(
        settings.derived_zip,
        sep=";",
        usecols=usecols,
        parse_dates=["Date"],
        dtype={
            "Ticker": "string",
            settings.pe_column: "float32",
            "Market-Cap": "float32",
        },
        chunksize=250_000,
    )

    for chunk_idx, chunk in enumerate(reader, start=1):
        chunk["Ticker"] = _normalize_tickers(chunk["Ticker"])
        chunk = chunk.dropna(subset=["Ticker", "Date"])
        chunk = chunk[chunk["Ticker"].isin(valid_tickers)]
        if chunk.empty:
            continue

        chunk = chunk.rename(
            columns={settings.pe_column: "pe", "Market-Cap": "market_cap"}
        )
        chunk = chunk[["Date", "Ticker", "pe", "market_cap"]]
        pieces.append(chunk)
        total_rows += len(chunk)

        if chunk_idx % 10 == 0:
            print(f"  processed signal chunks: {chunk_idx} ({total_rows:,} rows kept)")

    if not pieces:
        raise ValueError("No usable PE signal rows were found in the derived dataset.")

    signal_df = pd.concat(pieces, ignore_index=True)
    signal_df = signal_df.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    signal_df["Ticker"] = signal_df["Ticker"].astype("category")
    signal_df = signal_df.sort_values(["Date", "Ticker"])
    signal_df = signal_df.set_index(["Date", "Ticker"])

    pe_panel = signal_df["pe"].unstack("Ticker").sort_index().astype("float32")
    market_cap_panel = (
        signal_df["market_cap"].unstack("Ticker").sort_index().astype("float32")
    )

    common = pe_panel.columns.intersection(sector_map.index)
    pe_panel = pe_panel.loc[:, common]
    market_cap_panel = market_cap_panel.reindex(columns=common)

    print(
        "Signal panel ready: "
        f"{len(pe_panel.index):,} dates x {len(pe_panel.columns):,} tickers"
    )
    return pe_panel, market_cap_panel


def _winsorize_cross_section(
    panel: pd.DataFrame, std_multiplier: float
) -> pd.DataFrame:
    mean = panel.mean(axis=1)
    std = panel.std(axis=1)
    lower = mean - std_multiplier * std
    upper = mean + std_multiplier * std
    return panel.clip(lower=lower, upper=upper, axis=0).astype("float32")


def _compute_daily_alpha_panel(
    pe_panel: pd.DataFrame,
    sector_map: pd.Series,
    settings: PeSectorAlphaSettings,
) -> pd.DataFrame:
    print("Computing alpha inputs...")
    filled = pe_panel.ffill(limit=settings.backfill_limit)
    winsorized = _winsorize_cross_section(filled, settings.winsor_std)

    print(
        "Computing rolling z-scores on daily panel "
        f"({len(winsorized.index):,} dates)..."
    )
    sampled: dict[str, np.ndarray] = {}

    for idx, ticker in enumerate(winsorized.columns, start=1):
        series = winsorized[ticker]
        roll = series.rolling(settings.z_window, min_periods=settings.min_periods)
        zscore = -((series - roll.mean()) / roll.std())
        sampled[str(ticker)] = zscore.to_numpy(dtype="float32", na_value=np.nan)

        if idx % 500 == 0:
            print(f"  z-score progress: {idx:,}/{len(winsorized.columns):,} tickers")

    alpha = pd.DataFrame(sampled, index=winsorized.index, dtype="float32")
    alpha = alpha.replace([np.inf, -np.inf], np.nan)

    # Available local source only provides a static industry mapping. Treating
    # it as a time-series label and forward-filling by instrument reduces to the
    # same labels on every date, which matches the reference logic under this
    # data constraint.
    sector_aligned = sector_map.reindex(alpha.columns)
    for sector in sector_aligned.dropna().unique():
        tickers = sector_aligned[sector_aligned == sector].index
        group = alpha.loc[:, tickers]
        alpha.loc[:, tickers] = group.sub(group.mean(axis=1), axis=0)

    return alpha.astype("float32")


def _build_portfolios(
    alpha: pd.DataFrame,
    market_cap_panel: pd.DataFrame,
    sector_map: pd.Series,
    settings: PeSectorAlphaSettings,
) -> tuple[
    dict[dt.date, pd.DataFrame],
    dict[dt.date, pd.DataFrame],
    pd.DataFrame,
    pd.DataFrame,
]:
    # SimFin derived daily data can land on month-end calendar dates where
    # market-cap is missing. A short forward-fill keeps the dynamic universe
    # anchored to the latest observable trading-day market value.
    market_cap = market_cap_panel.ffill(limit=5).reindex(alpha.index)
    if settings.universe_size > 0:
        cap_rank = market_cap.rank(axis=1, method="first", ascending=False)
        eligible_alpha = alpha.where(cap_rank <= settings.universe_size)
    else:
        eligible_alpha = alpha

    portfolios: dict[dt.date, pd.DataFrame] = {}
    long_short_portfolios: dict[dt.date, pd.DataFrame] = {}
    combined_rows: list[pd.DataFrame] = []
    long_short_rows: list[pd.DataFrame] = []

    for date, row in eligible_alpha.iterrows():
        ranked = row.dropna().sort_values(ascending=False)
        if ranked.empty:
            continue

        longs = ranked.head(settings.holdings)
        shorts = ranked.tail(settings.short_holdings).sort_values()
        if longs.empty:
            continue

        portfolio = pd.DataFrame(
            {
                "Ticker": longs.index.astype(str),
                "Alpha": longs.astype(float).values,
                "Sector": sector_map.reindex(longs.index).astype("string").values,
            }
        )
        portfolio.insert(0, "Rank", np.arange(1, len(portfolio) + 1))
        portfolios[date.date()] = portfolio

        export_df = portfolio.copy()
        export_df.insert(0, "TradeDate", date.date().isoformat())
        combined_rows.append(export_df)

        if not shorts.empty:
            short_df = pd.DataFrame(
                {
                    "Ticker": shorts.index.astype(str),
                    "Alpha": shorts.astype(float).values,
                    "Sector": sector_map.reindex(shorts.index).astype("string").values,
                    "Side": "SHORT",
                }
            )
            short_df.insert(0, "Rank", np.arange(1, len(short_df) + 1))
            long_df = portfolio.copy()
            long_df["Side"] = "LONG"
            long_short_df = pd.concat([long_df, short_df], ignore_index=True)
            long_short_portfolios[date.date()] = long_short_df

            ls_export = long_short_df.copy()
            ls_export.insert(0, "TradeDate", date.date().isoformat())
            long_short_rows.append(ls_export)

    if not portfolios:
        raise ValueError("No rebalance portfolios were generated from the alpha.")

    combined = (
        pd.concat(combined_rows, ignore_index=True) if combined_rows else pd.DataFrame()
    )
    long_short_combined = (
        pd.concat(long_short_rows, ignore_index=True)
        if long_short_rows
        else pd.DataFrame()
    )
    return portfolios, long_short_portfolios, combined, long_short_combined


def _export_portfolios(
    portfolios: dict[dt.date, pd.DataFrame],
    combined: pd.DataFrame,
    *,
    base_dir: Path,
    snapshot_name: str,
) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

    for trade_date, df in portfolios.items():
        year_dir = base_dir / f"{trade_date.year}"
        year_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "trade_date": trade_date.isoformat(),
            "rows": df.to_dict(orient="records"),
        }
        out_path = year_dir / f"{trade_date.isoformat()}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if not combined.empty:
        combined.to_csv(OUTPUT_DIR / snapshot_name, index=False)


def _load_price_panel(
    settings: PeSectorAlphaSettings,
    needed_tickers: set[str],
    start_date: pd.Timestamp,
) -> pd.DataFrame:
    print(
        f"Loading adjusted-close prices for {len(needed_tickers):,} tickers from "
        f"{settings.prices_zip.name}..."
    )

    usecols = ["Ticker", "Date", "Adj. Close", "Close"]
    pieces: list[pd.DataFrame] = []
    total_rows = 0

    reader = pd.read_csv(
        settings.prices_zip,
        sep=";",
        usecols=usecols,
        parse_dates=["Date"],
        dtype={
            "Ticker": "string",
            "Adj. Close": "float32",
            "Close": "float32",
        },
        chunksize=500_000,
    )

    for chunk_idx, chunk in enumerate(reader, start=1):
        chunk["Ticker"] = _normalize_tickers(chunk["Ticker"])
        chunk = chunk.dropna(subset=["Ticker", "Date"])
        chunk = chunk[chunk["Ticker"].isin(needed_tickers)]
        chunk = chunk[chunk["Date"] >= start_date]
        if chunk.empty:
            continue

        chunk["price"] = chunk["Adj. Close"].fillna(chunk["Close"])
        chunk = chunk.dropna(subset=["price"])
        chunk = chunk[["Date", "Ticker", "price"]]
        pieces.append(chunk)
        total_rows += len(chunk)

        if chunk_idx % 10 == 0:
            print(f"  processed price chunks: {chunk_idx} ({total_rows:,} rows kept)")

    if not pieces:
        raise ValueError("No usable price rows were found for the selected tickers.")

    prices_df = pd.concat(pieces, ignore_index=True)
    prices_df = prices_df.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    prices_df["Ticker"] = prices_df["Ticker"].astype("category")
    prices_df = prices_df.sort_values(["Date", "Ticker"]).set_index(["Date", "Ticker"])
    price_panel = prices_df["price"].unstack("Ticker").sort_index().astype("float32")
    price_panel = price_panel.ffill()

    print(
        "Price panel ready: "
        f"{len(price_panel.index):,} dates x {len(price_panel.columns):,} tickers"
    )
    return price_panel


def _simulate_equal_weight_portfolio(
    prices: pd.DataFrame,
    portfolios: dict[dt.date, pd.DataFrame],
    initial_cash: float,
) -> tuple[pd.Series, pd.DataFrame]:
    ordered_dates = sorted(portfolios)
    valuation_parts: list[pd.Series] = []
    diagnostics: list[dict[str, Any]] = []
    capital = float(initial_cash)

    for idx, signal_date in enumerate(ordered_dates):
        signal_ts = pd.Timestamp(signal_date)
        next_signal_ts = (
            pd.Timestamp(ordered_dates[idx + 1])
            if idx + 1 < len(ordered_dates)
            else prices.index.max()
        )

        active_dates = prices.index[
            (prices.index > signal_ts) & (prices.index <= next_signal_ts)
        ]
        if active_dates.empty:
            continue

        tickers = [
            ticker for ticker in portfolios[signal_date]["Ticker"].astype(str)
            if ticker in prices.columns
        ]
        period_prices = prices.loc[active_dates, tickers]
        tradable = period_prices.columns[period_prices.iloc[0].notna()]
        period_prices = period_prices.loc[:, tradable].ffill()

        diagnostics.append(
            {
                "signal_date": signal_date.isoformat(),
                "selected_count": len(tickers),
                "tradable_count": len(tradable),
            }
        )

        if period_prices.empty:
            valuation_parts.append(pd.Series(capital, index=active_dates))
            continue

        relatives = period_prices.div(period_prices.iloc[0])
        period_path = capital * relatives.mean(axis=1, skipna=True)
        valuation_parts.append(period_path)
        capital = float(period_path.iloc[-1])

    if not valuation_parts:
        raise ValueError("Portfolio simulation produced no valuation points.")

    portfolio_value = pd.concat(valuation_parts).sort_index()
    portfolio_value = portfolio_value[~portfolio_value.index.duplicated(keep="last")]
    start_marker = portfolio_value.index.min() - pd.Timedelta(days=1)
    portfolio_value = pd.concat(
        [pd.Series({start_marker: float(initial_cash)}), portfolio_value]
    )

    diagnostics_df = pd.DataFrame(diagnostics)
    return portfolio_value.astype(float), diagnostics_df


def _simulate_dollar_neutral_portfolio(
    prices: pd.DataFrame,
    portfolios: dict[dt.date, pd.DataFrame],
    initial_cash: float,
) -> tuple[pd.Series, pd.DataFrame]:
    ordered_dates = sorted(portfolios)
    valuation_parts: list[pd.Series] = []
    diagnostics: list[dict[str, Any]] = []
    capital = float(initial_cash)

    for idx, signal_date in enumerate(ordered_dates):
        signal_ts = pd.Timestamp(signal_date)
        next_signal_ts = (
            pd.Timestamp(ordered_dates[idx + 1])
            if idx + 1 < len(ordered_dates)
            else prices.index.max()
        )

        active_dates = prices.index[
            (prices.index > signal_ts) & (prices.index <= next_signal_ts)
        ]
        if active_dates.empty:
            continue

        book = portfolios[signal_date]
        long_tickers = [
            ticker
            for ticker in book.loc[book["Side"] == "LONG", "Ticker"].astype(str)
            if ticker in prices.columns
        ]
        short_tickers = [
            ticker
            for ticker in book.loc[book["Side"] == "SHORT", "Ticker"].astype(str)
            if ticker in prices.columns
        ]

        long_prices = prices.loc[active_dates, long_tickers]
        short_prices = prices.loc[active_dates, short_tickers]
        tradable_longs = long_prices.columns[long_prices.iloc[0].gt(0)]
        tradable_shorts = short_prices.columns[short_prices.iloc[0].gt(0)]
        long_prices = (
            long_prices.loc[:, tradable_longs].ffill().where(lambda df: df > 0)
        )
        short_prices = (
            short_prices.loc[:, tradable_shorts].ffill().where(lambda df: df > 0)
        )

        diagnostics.append(
            {
                "signal_date": signal_date.isoformat(),
                "selected_longs": len(long_tickers),
                "selected_shorts": len(short_tickers),
                "tradable_longs": len(tradable_longs),
                "tradable_shorts": len(tradable_shorts),
            }
        )

        if long_prices.empty and short_prices.empty:
            valuation_parts.append(pd.Series(capital, index=active_dates))
            continue

        if long_prices.empty:
            long_leg_log_returns = pd.Series(0.0, index=active_dates)
        else:
            long_leg_log_returns = np.log(long_prices / long_prices.shift(1))
            long_leg_log_returns = long_leg_log_returns.replace(
                [np.inf, -np.inf], np.nan
            ).fillna(0.0)
            long_leg_log_returns = long_leg_log_returns.mean(axis=1)

        if short_prices.empty:
            short_leg_log_returns = pd.Series(0.0, index=active_dates)
        else:
            short_leg_log_returns = np.log(short_prices / short_prices.shift(1))
            short_leg_log_returns = short_leg_log_returns.replace(
                [np.inf, -np.inf], np.nan
            ).fillna(0.0)
            short_leg_log_returns = short_leg_log_returns.mean(axis=1)

        portfolio_log_returns = 0.5 * long_leg_log_returns - 0.5 * short_leg_log_returns
        period_path = capital * np.exp(portfolio_log_returns.cumsum())
        valuation_parts.append(period_path)
        capital = float(period_path.iloc[-1])

    if not valuation_parts:
        raise ValueError("Dollar-neutral simulation produced no valuation points.")

    portfolio_value = pd.concat(valuation_parts).sort_index()
    portfolio_value = portfolio_value[~portfolio_value.index.duplicated(keep="last")]
    start_marker = portfolio_value.index.min() - pd.Timedelta(days=1)
    portfolio_value = pd.concat(
        [pd.Series({start_marker: float(initial_cash)}), portfolio_value]
    )
    diagnostics_df = pd.DataFrame(diagnostics)
    return portfolio_value.astype(float), diagnostics_df


def _build_benchmark_series(
    prices: pd.DataFrame, *, ticker: str, initial_cash: float, start_date: pd.Timestamp
) -> pd.Series | None:
    if ticker not in prices.columns:
        return None

    bench = prices[ticker].dropna()
    bench = bench[bench.index >= start_date]
    if bench.empty:
        return None

    series = float(initial_cash) * (bench / bench.iloc[0])
    start_marker = series.index.min() - pd.Timedelta(days=1)
    return pd.concat([pd.Series({start_marker: float(initial_cash)}), series]).astype(
        float
    )


def _compute_metrics(value_series: pd.Series, initial_cash: float) -> dict[str, Any]:
    series = value_series.dropna().sort_index()
    if series.empty:
        raise ValueError("Cannot compute metrics from an empty series.")

    returns = series.pct_change().dropna()
    effective_start = (
        returns.index.min().date()
        if not returns.empty
        else series.index.min().date()
    )
    end_date = series.index.max().date()
    final_value = float(series.iloc[-1])
    total_return = final_value / float(initial_cash) - 1.0

    duration_days = max(1, (end_date - effective_start).days)
    duration_years = duration_days / 365.25
    annualized_return = (
        (final_value / float(initial_cash)) ** (1.0 / duration_years)
    ) - 1.0

    drawdown = series / series.cummax() - 1.0
    max_drawdown = abs(float(drawdown.min())) * 100.0

    metrics: dict[str, Any] = {
        "start_date": effective_start,
        "end_date": end_date,
        "initial_value": float(initial_cash),
        "final_value": final_value,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": float(max_drawdown),
    }

    if len(returns) > 1:
        sigma = returns.std(ddof=1)
        if sigma and not pd.isna(sigma):
            metrics["sharpe"] = float((returns.mean() / sigma) * np.sqrt(252.0))

    return metrics


def _serialize_settings(settings: PeSectorAlphaSettings) -> dict[str, Any]:
    payload = asdict(settings)
    payload["pe_column"] = settings.pe_column
    for key in ["derived_zip", "prices_zip", "companies_zip", "industries_zip"]:
        payload[key] = str(payload[key])
    return payload


def main() -> None:
    """Run the PE sector-neutral alpha backtest."""

    settings = PeSectorAlphaSettings.from_env()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("--- Running PE Sector-Neutral Alpha Backtest ---")
    print(
        "Assumptions: "
        f"PE={settings.pe_column}, frequency={settings.rebalance_frequency}, "
        f"universe={settings.universe_size}, long_holdings={settings.holdings}, "
        f"short_holdings={settings.short_holdings}"
    )

    sector_map = _load_sector_map(settings)
    pe_panel, market_cap_panel = _load_signal_panels(settings, sector_map)
    rebalance_dates = _select_rebalance_dates(
        pe_panel.index, settings.rebalance_frequency
    )

    daily_alpha = _compute_daily_alpha_panel(pe_panel, sector_map, settings)
    daily_alpha = daily_alpha.dropna(how="all")
    daily_alpha_path = OUTPUT_DIR / "daily_alpha.pkl.gz"
    print(f"Saving daily final_alpha panel to {daily_alpha_path.name}...")
    daily_alpha.to_pickle(daily_alpha_path, compression="gzip")

    alpha = daily_alpha.reindex(rebalance_dates).dropna(how="all")
    market_cap_panel = market_cap_panel.reindex(daily_alpha.index)

    (
        portfolios,
        long_short_portfolios,
        combined,
        long_short_combined,
    ) = _build_portfolios(alpha, market_cap_panel, sector_map, settings)
    _export_portfolios(
        portfolios,
        combined,
        base_dir=PORTFOLIO_DIR,
        snapshot_name="portfolio_snapshots.csv",
    )
    if long_short_portfolios:
        _export_portfolios(
            long_short_portfolios,
            long_short_combined,
            base_dir=LONG_SHORT_PORTFOLIO_DIR,
            snapshot_name="long_short_portfolio_snapshots.csv",
        )
    del pe_panel
    del market_cap_panel
    del alpha

    all_needed_tickers = set(combined["Ticker"].astype(str).unique().tolist())
    if not long_short_combined.empty:
        all_needed_tickers.update(long_short_combined["Ticker"].astype(str).unique())
    all_needed_tickers.add("SPY")

    first_signal_date = pd.Timestamp(min(portfolios))
    prices = _load_price_panel(settings, all_needed_tickers, first_signal_date)
    portfolio_value, diagnostics = _simulate_equal_weight_portfolio(
        prices, portfolios, settings.initial_cash
    )
    diagnostics.to_csv(OUTPUT_DIR / "rebalance_diagnostics.csv", index=False)
    portfolio_value.to_csv(
        OUTPUT_DIR / "portfolio_value.csv", header=["LongOnlyPortfolioValue"]
    )

    long_short_value = None
    long_short_metrics = None
    if long_short_portfolios:
        long_short_value, long_short_diagnostics = _simulate_dollar_neutral_portfolio(
            prices, long_short_portfolios, settings.initial_cash
        )
        long_short_diagnostics.to_csv(
            OUTPUT_DIR / "long_short_rebalance_diagnostics.csv", index=False
        )
        long_short_value.to_csv(
            OUTPUT_DIR / "long_short_portfolio_value.csv",
            header=["LongShortPortfolioValue"],
        )
        long_short_metrics = _compute_metrics(long_short_value, settings.initial_cash)

    benchmark_value = _build_benchmark_series(
        prices,
        ticker="SPY",
        initial_cash=settings.initial_cash,
        start_date=portfolio_value.index[1],
    )
    benchmark_metrics = (
        _compute_metrics(benchmark_value, settings.initial_cash)
        if benchmark_value is not None
        else None
    )
    if benchmark_value is not None:
        benchmark_value.to_csv(OUTPUT_DIR / "benchmark_value.csv", header=["SPY"])

    long_only_metrics = _compute_metrics(portfolio_value, settings.initial_cash)

    report_path = OUTPUT_DIR / "pe_sector_alpha_returns.png"
    generate_report(
        metrics=long_only_metrics,
        title="PE Sector-Neutral Alpha Backtest Results",
        portfolio_value=portfolio_value,
        output_png=report_path,
        benchmark_value=benchmark_value,
        benchmark_label="SPY",
        benchmark_metrics=benchmark_metrics,
        report_mode="both" if benchmark_value is not None else "strategy_only",
        with_underwater=True,
        index_to_100=True,
        use_log_scale=False,
        show_rolling=False,
        show_heatmap=True,
    )

    long_short_report_path = None
    if long_short_value is not None and long_short_metrics is not None:
        long_short_report_path = OUTPUT_DIR / "pe_sector_alpha_long_short_returns.png"
        generate_report(
            metrics=long_short_metrics,
            title="PE Sector-Neutral Alpha Long-Short Backtest Results",
            portfolio_value=long_short_value,
            output_png=long_short_report_path,
            benchmark_value=None,
            report_mode="strategy_only",
            with_underwater=True,
            index_to_100=True,
            use_log_scale=False,
            show_rolling=False,
            show_heatmap=True,
        )

    summary = {
        "settings": _serialize_settings(settings),
        "daily_alpha_path": str(daily_alpha_path),
        "long_only_metrics": long_only_metrics,
        "long_short_metrics": long_short_metrics,
        "benchmark_metrics": benchmark_metrics,
        "output_png": str(report_path),
        "long_short_output_png": (
            str(long_short_report_path) if long_short_report_path is not None else None
        ),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"Summary written to {OUTPUT_DIR / 'summary.json'}")


__all__ = [
    "PeSectorAlphaSettings",
    "_build_benchmark_series",
    "_build_portfolios",
    "_compute_daily_alpha_panel",
    "_compute_metrics",
    "_load_sector_map",
    "_normalize_tickers",
    "_select_rebalance_dates",
    "_simulate_equal_weight_portfolio",
    "_simulate_dollar_neutral_portfolio",
    "calculate_alpha_reference",
    "main",
]
