"""Data preparation module

Provides portfolio loading and data alignment functionality, unified handling of Excel reading and database query logic.
"""

import datetime
import sqlite3
import sys
import json
from pathlib import Path

import backtrader as bt
import pandas as pd


class DividendPandasData(bt.feeds.PandasData):
    """PandasData feed extended with dividend support."""

    lines = ("dividend",)
    params = (("dividend", "Dividend"),)


def tidy_ticker(col: pd.Series) -> pd.Series:
    """Clean ticker symbols

    Args:
        col: Series containing ticker symbols

    Returns:
        pd.Series: Cleaned ticker symbols Series
    """
    return (
        col.astype("string")
        .str.upper()
        .str.strip()
        .str.replace(r"_DELISTED$", "", regex=True)
        .replace({"": pd.NA})
    )



def load_portfolios(
    portfolio_path: Path, is_ai_selection: bool = False
) -> dict[datetime.date, pd.DataFrame]:
    """Load portfolio data from Excel or JSON.

    Args:
        portfolio_path: Excel workbook path or JSON file/directory path
        is_ai_selection: Whether it's AI selection version, affects column name processing logic

    Returns:
        Dict[datetime.date, pd.DataFrame]: Portfolio dictionary with rebalance dates as keys

    Raises:
        FileNotFoundError: When file or directory does not exist
    """
    if not portfolio_path.exists():
        raise FileNotFoundError(f"Portfolio file not found: {portfolio_path}")

    portfolios: dict[datetime.date, pd.DataFrame] = {}

    if portfolio_path.suffix.lower() == ".json" or portfolio_path.is_dir():
        json_files = (
            [portfolio_path]
            if portfolio_path.is_file()
            else sorted(portfolio_path.rglob("*.json"))
        )
        for fp in json_files:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue

            trade_date = data.get("trade_date")
            if not trade_date:
                continue

            key = "picks" if is_ai_selection else "rows"
            rows = data.get(key, [])
            if not rows:
                continue

            df = pd.DataFrame(rows)
            if "ticker" in df.columns and "Ticker" not in df.columns:
                df.rename(columns={"ticker": "Ticker"}, inplace=True)

            if "Ticker" in df.columns:
                df["Ticker"] = tidy_ticker(df["Ticker"])
                df = df.dropna(subset=["Ticker"])
                if not df.empty:
                    portfolios[pd.to_datetime(trade_date).date()] = df

        return portfolios

    xls = pd.read_excel(portfolio_path, sheet_name=None, engine="openpyxl")

    for date_str, df in xls.items():
        if df.empty:
            continue

        if is_ai_selection and "ticker" in df.columns and "Ticker" not in df.columns:
            df.rename(columns={"ticker": "Ticker"}, inplace=True)

        if "Ticker" in df.columns:
            df["Ticker"] = tidy_ticker(df["Ticker"])
            df = df.dropna(subset=["Ticker"])
            if not df.empty:
                portfolios[pd.to_datetime(date_str).date()] = df

    return portfolios


def load_price_feeds(
    db_path: Path, tickers: set[str], start_date: datetime.date, end_date: datetime.date
) -> dict[str, DividendPandasData]:
    """Load price data from database and create Backtrader data feeds

    Args:
        db_path: Database file path
        tickers: Set of ticker symbols to load
        start_date: Start date
        end_date: End date

    Returns:
        Dict[str, DividendPandasData]: Data feed dictionary with ticker symbols as keys

    Raises:
        FileNotFoundError: When database file does not exist
        ValueError: When no trading day data is found
    """
    print(f"Loading and preparing all price data from {start_date} to {end_date}...")

    if not db_path.exists():
        print(f"[ERROR] 数据库文件不存在: {db_path}", file=sys.stderr)
        raise FileNotFoundError(f"Database file not found: {db_path}")

    con = sqlite3.connect(db_path)

    try:
        # Get master trading day index
        date_query = (
            "SELECT DISTINCT Date FROM share_prices "
            "WHERE Date >= ? AND Date <= ? ORDER BY Date"
        )
        master_dates_df = pd.read_sql_query(
            date_query,
            con,
            params=[start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
            parse_dates=["Date"],
        )

        if master_dates_df.empty:
            raise ValueError(
                "No trading days found in the database for the specified date range."
            )

        master_index = pd.to_datetime(master_dates_df["Date"])
        print(f"Master timeline created with {len(master_index)} trading days.")

        # Bulk query all stock data
        tickers_list = list(tickers)
        placeholders = ",".join(["?" for _ in tickers_list])
        bulk_query = f"""
            SELECT Date, Ticker, Open, High, Low, Close, Volume, Dividend 
            FROM share_prices 
            WHERE Ticker IN ({placeholders}) AND Date >= ? AND Date <= ? 
            ORDER BY Ticker, Date
        """

        params = tickers_list + [
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        ]

        all_data = pd.read_sql_query(
            bulk_query, con, params=params, parse_dates=["Date"]
        )

        # Deduplication fix: remove possible duplicate data
        all_data.drop_duplicates(subset=["Ticker", "Date"], keep="last", inplace=True)

        # Create data feeds for each stock
        data_feeds = {}

        price_columns = ["Open", "High", "Low", "Close", "Volume"]

        for ticker, group in all_data.groupby("Ticker"):
            group = group.set_index("Date")

            # Reindex to master trading day timeline
            group = group.reindex(master_index)

            # Forward fill price-related columns without affecting dividends
            group[price_columns] = group[price_columns].ffill()

            # Fill missing values in dividend column without forward filling
            group["Dividend"] = group["Dividend"].fillna(0.0)

            # Remove still missing rows (usually early data for newly listed stocks)
            group = group.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

            if not group.empty:
                # Create Backtrader data feed with dividend support
                bt_feed = DividendPandasData(
                    dataname=group, openinterest=None, name=ticker
                )
                object.__setattr__(bt_feed, "dataname", group)
                data_feeds[ticker] = bt_feed
                print(f"Prepared data for {ticker}: {len(group)} rows")
            else:
                print(f"Warning: No valid data for {ticker} after processing")

        print(f"Successfully prepared data feeds for {len(data_feeds)} tickers")
        return data_feeds

    finally:
        con.close()


def load_spy_data(
    db_path: Path,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    ticker: str = "SPY",
) -> pd.DataFrame:
    """Load SPY data from database

    Args:
        db_path: Database file path
        start_date: Start date
        end_date: End date
        ticker: Ticker symbol, defaults to SPY

    Returns:
        pd.DataFrame: SPY price data

    Raises:
        FileNotFoundError: When database file does not exist
        ValueError: When no data is found
    """
    print(f"Loading {ticker} data from database: {db_path.name}...")

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    con = sqlite3.connect(db_path)

    try:
        query = """
        SELECT Date, Open, High, Low, Close, Volume, Dividend
        FROM share_prices 
        WHERE Ticker = ? AND Date >= ? AND Date <= ?
        ORDER BY Date
        """

        data = pd.read_sql_query(
            query,
            con,
            params=[
                ticker,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ],
            parse_dates=["Date"],
        )

        if data.empty:
            raise ValueError(
                f"No {ticker} data found in database for the specified date range: "
                f"{start_date} to {end_date}"
            )

        data.set_index("Date", inplace=True)
        data["Dividend"] = data["Dividend"].fillna(0.0)

        print(
            f"Loaded {len(data)} rows for {ticker} from "
            f"{data.index.min().date()} to {data.index.max().date()}."
        )

        return data

    finally:
        con.close()
