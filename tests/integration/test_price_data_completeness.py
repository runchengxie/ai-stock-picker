import sqlite3

import pandas as pd
import pytest
from stock_analysis.shared.utils.paths import (
    DB_PATH,
    QUANT_PORTFOLIO_FILE,
)

PORTFOLIO_FILE = QUANT_PORTFOLIO_FILE

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

# --- Test Constants Configuration ---
# A quarter has approximately 252/4 = 63 trading days
TRADING_DAYS_IN_QUARTER = 63
# We require a price data coverage of at least 90% to tolerate
# holidays or minor data gaps
MIN_COVERAGE_RATIO = 0.90


# --- Pytest Fixtures: Prepare data and connections for testing ---


@pytest.fixture(scope="session")
def db_connection():
    """
    Creates a database connection fixture.
    It is created only once for the entire test session and
    is automatically closed at the end.
    """
    if not DB_PATH.exists():
        pytest.skip(f"Database file not found, skipping this test: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    cursor = con.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM share_prices")
        if cursor.fetchone()[0] == 0:
            raise RuntimeError("share_prices table empty")
    except Exception:
        con.close()
        pytest.skip(
            "share_prices table not found or contains no data, skipping this test"
        )

    yield con
    con.close()


@pytest.fixture(scope="session")
def portfolio_excel_file() -> pd.ExcelFile:
    """Loads the portfolio Excel file as a reusable test resource."""
    if not PORTFOLIO_FILE.exists():
        pytest.skip(f"Portfolio file not found, skipping this test: {PORTFOLIO_FILE}")
    with pd.ExcelFile(PORTFOLIO_FILE) as xls:
        yield xls


# --- Helper Function for Dynamically Generating Test Cases ---


def get_portfolio_sheet_names():
    """Helper function: Reads sheet names from the Excel file
    for parameterization."""
    if not PORTFOLIO_FILE.exists():
        return []
    with pd.ExcelFile(PORTFOLIO_FILE) as xls:
        return xls.sheet_names


# --- Pytest Test Functions ---


@pytest.mark.parametrize("sheet_name", get_portfolio_sheet_names())
def test_price_data_is_complete_for_holding_period(
    sheet_name: str,
    db_connection: sqlite3.Connection,
    portfolio_excel_file: pd.ExcelFile,
):
    """
    For each stock in the portfolio, verifies that its price data is complete
    for the subsequent holding period.
    """
    # 1. Prepare test period and parameters
    rebalance_date = pd.to_datetime(sheet_name)
    period_start = rebalance_date
    # The holding period is the next quarter
    period_end = period_start + pd.DateOffset(months=3)

    # Calculate the minimum required data points for this period
    min_required_days = int(TRADING_DAYS_IN_QUARTER * MIN_COVERAGE_RATIO)

    # Read the list of stocks for this period from the Excel file
    df_portfolio = portfolio_excel_file.parse(sheet_name)
    if "Ticker" not in df_portfolio.columns or df_portfolio.empty:
        pytest.skip(
            f"Ticker column not found or content is empty in sheet '{sheet_name}'."
        )

    portfolio_tickers = df_portfolio["Ticker"].unique().tolist()

    # 2. Iterate through each stock and check its data completeness
    data_completeness_errors = []

    for ticker in portfolio_tickers:
        # Use a parameterized query to prevent SQL injection
        query = """
        SELECT COUNT(Date)
        FROM share_prices
        WHERE Ticker = ? AND Date >= ? AND Date < ?
        """

        # Convert dates to a string format recognizable by SQLite
        params = (ticker, str(period_start.date()), str(period_end.date()))

        cursor = db_connection.cursor()
        cursor.execute(query, params)
        count = cursor.fetchone()[0]

        if count < min_required_days:
            error_msg = (
                f"{ticker}: Price data is incomplete for the period "
                f"{period_start.date()} to {period_end.date()}. "
                f"Expected at least {min_required_days} days, but found only {count}."
            )
            data_completeness_errors.append(error_msg)

    # 3. After all checks are complete, perform the final assertion
    assert not data_completeness_errors, (
        "\nFound price data completeness issues for the holding period after "
        f"rebalance date {rebalance_date.date()}:\n"
        + "\n".join(f"  - {err}" for err in data_completeness_errors)
    )
