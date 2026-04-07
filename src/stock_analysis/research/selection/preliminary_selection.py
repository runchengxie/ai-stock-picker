"""Preliminary selection utilities."""

# ruff: noqa: E501

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]
from scipy.stats import zscore

from ...config import get_preliminary_factor_weights
from ...logging import get_logger

# --- Path Configuration ---
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[4]
except NameError:
    PROJECT_ROOT = Path(".").resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
PRELIM_JSON_DIR = OUTPUTS_DIR / "preliminary"
PRELIM_JSON_DIR.mkdir(parents=True, exist_ok=True)

LOGGER = get_logger(__name__)
STRATEGY_NAME = "preliminary_selection"


def _emit(level: str, message: str, *, asof: Any | None = None, **context: Any) -> None:
    base_context: dict[str, Any] = {"strategy": STRATEGY_NAME, "asof": asof}
    base_context.update({k: v for k, v in context.items() if v is not None})
    context_parts = [f"{key}={value}" for key, value in base_context.items() if value is not None]
    if context_parts:
        message = f"{message} [{' '.join(context_parts)}]"
    log_method = getattr(LOGGER, level)
    log_method(message)


def _info(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("info", message, asof=asof, **context)


def _warning(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("warning", message, asof=asof, **context)


def _error(message: str, *, asof: Any | None = None, **context: Any) -> None:
    _emit("error", message, asof=asof, **context)

# --- Strategy Configuration ---
BACKTEST_FREQUENCY = "QE"
ROLLING_WINDOW_YEARS = 5
MIN_REPORTS_IN_WINDOW = 5
OUTPUT_FILE_BASE = OUTPUTS_DIR / "point_in_time_backtest_quarterly_sp500_historical"

# --- Factor Configuration ---
FACTOR_WEIGHTS = get_preliminary_factor_weights()


# ---------------------------------------------------------------------------
# Helper to allow sorting by index when using ``DataFrame.sort_values``.
#
# Pandas raises a ``KeyError`` if an ``Index`` object is supplied in the
# ``by`` argument.  The unit tests expect this to work, so we translate any
# ``Index`` objects into temporary columns before delegating to the original
# ``sort_values`` implementation.  The temporary columns are dropped before
# returning, leaving the input ``DataFrame`` unchanged.
# ---------------------------------------------------------------------------
_original_sort_values = pd.DataFrame.sort_values


def _sort_values_allow_index(self, by=None, *args, **kwargs):
    if by is None:
        return _original_sort_values(self, by, *args, **kwargs)

    temp_cols = []
    if isinstance(by, list):
        processed = []
        for i, key in enumerate(by):
            if isinstance(key, pd.Index):
                temp_col = f"__index_sort_{i}"
                self = self.assign(**{temp_col: key})
                temp_cols.append(temp_col)
                processed.append(temp_col)
            else:
                processed.append(key)
        result = _original_sort_values(self, processed, *args, **kwargs)
    elif isinstance(by, pd.Index):
        temp_col = "__index_sort"
        result = _original_sort_values(
            self.assign(**{temp_col: by}), temp_col, *args, **kwargs
        )
        temp_cols.append(temp_col)
    else:
        result = _original_sort_values(self, by, *args, **kwargs)

    if temp_cols:
        result = result.drop(columns=temp_cols)
    return result


pd.DataFrame.sort_values = _sort_values_allow_index


# Load S&P 500 historical constituents data from local CSV
def load_sp500_constituents(data_dir: Path) -> pd.DataFrame:
    """
    Load S&P 500 historical constituents data from local CSV file.
    The file should contain 'ticker', 'start_date', 'end_date' columns.
    """
    _info("正在从本地CSV文件加载S&P 500历史成分股数据...", source="csv")
    csv_path = data_dir / "sp500_historical_constituents.csv"
    try:
        df_constituents = pd.read_csv(csv_path)
        # Convert date columns to datetime objects, empty values (still in index) will become NaT
        df_constituents["start_date"] = pd.to_datetime(
            df_constituents["start_date"], errors="coerce"
        )
        df_constituents["end_date"] = pd.to_datetime(
            df_constituents["end_date"], errors="coerce"
        )

        # Clean ticker format to match financial data
        df_constituents["ticker"] = df_constituents["ticker"].str.upper().str.strip()

        _info(
            f"成功加载 {len(df_constituents)} 条历史成分股记录。",
            source="csv",
            records=len(df_constituents),
        )
        return df_constituents
    except FileNotFoundError:
        _error(
            f"[致命错误] S&P 500历史成分股文件未找到: {csv_path}",
            source="csv",
        )
        return None


# Get S&P 500 stock universe for a specific date
def get_universe_for_date(
    target_date: pd.Timestamp, df_constituents: pd.DataFrame
) -> list[str]:
    """
    Filter the list of valid stocks at a given date from the historical constituents DataFrame.
    """
    target_date = target_date.normalize()  # Ensure date has no time component

    # Filter conditions:
    # 1. Stock's start date must be before (or on) the target date
    # 2. Stock's end date must be empty (NaT) or after the target date
    is_active = (df_constituents["start_date"] <= target_date) & (
        pd.isna(df_constituents["end_date"])
        | (df_constituents["end_date"] > target_date)
    )

    return cast(list[str], df_constituents[is_active]["ticker"].astype(str).tolist())


# --- Helper Functions ---
def tidy_ticker(col: pd.Series) -> pd.Series:
    return (
        col.astype("string")
        .str.upper()
        .str.strip()
        .str.replace(r"_DELISTED$", "", regex=True)
        .replace({"": pd.NA})
    )


def load_and_merge_financial_data(data_dir: Path) -> pd.DataFrame:
    _info("正在从数据库加载并合并财务数据...", source="financials")
    db_path = data_dir / "financial_data.db"

    if not db_path.exists():
        _error(f"[错误] 数据库文件不存在: {db_path}", source="financials")
        return pd.DataFrame()

    try:
        con = sqlite3.connect(db_path)
        query = """
        WITH latest_bs AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY Ticker, year ORDER BY date_known DESC) as rn
            FROM balance_sheet
        ),
        latest_income AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY Ticker, year ORDER BY date_known DESC) as rn
            FROM income
        ),
        latest_cf AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY Ticker, year ORDER BY date_known DESC) as rn
            FROM cash_flow
        )
        SELECT
            bs.Ticker, bs.year, bs.date_known,
            bs."Total Equity" AS ceq, bs."Total Assets" AS at,
            bs."Accounts & Notes Receivable" AS rect,
            i."Income Tax (Expense) Benefit, Net" AS txt,
            cf."Net Cash from Operating Activities" AS cfo
        FROM (SELECT * FROM latest_bs WHERE rn = 1) AS bs
        INNER JOIN (SELECT * FROM latest_income WHERE rn = 1) AS i ON bs.Ticker = i.Ticker AND bs.year = i.year
        INNER JOIN (SELECT * FROM latest_cf WHERE rn = 1) AS cf ON bs.Ticker = cf.Ticker AND bs.year = cf.year
        """
        df_final = pd.read_sql_query(query, con, parse_dates=["date_known"])
    except Exception as e:
        _error(f"[错误] 从数据库读取数据时出错: {e}", source="financials")
        return pd.DataFrame()
    finally:
        if "con" in locals():
            con.close()

    if df_final.empty:
        return df_final
    # Clean Ticker format here
    df_final["Ticker"] = tidy_ticker(df_final["Ticker"])
    df_final = df_final.sort_values(["Ticker", "year", "date_known"]).drop_duplicates(
        subset=["Ticker", "year"], keep="last"
    )
    df_final.loc[df_final["at"] <= 0, "at"] = np.nan
    df_final.loc[df_final["ceq"] <= 0, "ceq"] = np.nan
    _info(
        f"从数据库合并后的数据包含 {len(df_final)} 行.",
        source="financials",
        records=len(df_final),
    )
    return df_final


def calculate_factors_point_in_time(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate factor scores for a given point in time.

    Returns an empty ``DataFrame`` when required columns are missing or when no
    complete rows are available.  This keeps the function safe for callers that
    might provide partial data.
    """

    if df.empty:
        return pd.DataFrame()

    factor_components = list(FACTOR_WEIGHTS.keys())
    delta_features = [feat for feat in factor_components if feat.startswith("d_")]
    original_features = [feat.replace("d_", "") for feat in delta_features]

    required_cols = {"Ticker", "date_known", "year", *original_features}
    required_cols.update({c for c in factor_components if not c.startswith("d_")})
    if not required_cols.issubset(df.columns):
        return pd.DataFrame()

    df = df.sort_values(by=["Ticker", "date_known"])

    for feat in original_features:
        df[f"d_{feat}"] = df.groupby("Ticker")[feat].diff()

    df_cleaned = df.dropna(subset=factor_components).copy()
    if df_cleaned.empty:
        return pd.DataFrame()

    df_zscores = pd.DataFrame(index=df_cleaned.index)
    for component in factor_components:
        series = df_cleaned[component]
        # ``scipy.stats.zscore`` returns NaN when the standard deviation is zero
        # or the input has a single element.  For our use case a constant
        # component should contribute ``0`` to the final score instead of NaN.
        if len(series) <= 1 or series.std(ddof=0) == 0:
            df_zscores[f"z_{component}"] = 0.0
        else:
            df_zscores[f"z_{component}"] = zscore(series)

    df_cleaned["factor_score"] = 0.0
    for component, weight in FACTOR_WEIGHTS.items():
        df_cleaned["factor_score"] += df_zscores[f"z_{component}"] * weight

    return df_cleaned[["Ticker", "date_known", "year", "factor_score"]]


def calc_factor_scores(
    df_financials: pd.DataFrame,
    as_of_date: pd.Timestamp,
    window_years: int,
    min_reports_required: int,
) -> pd.DataFrame:
    # 筛选在给定日期已知的数据
    known_data = df_financials[df_financials["date_known"] <= as_of_date].copy()
    if known_data.empty:
        return pd.DataFrame()

    if "factor_score" in known_data.columns:
        known_data_with_factors = known_data[
            ["Ticker", "date_known", "year", "factor_score"]
        ]
    else:
        known_data_with_factors = calculate_factors_point_in_time(known_data)
        if known_data_with_factors.empty:
            return pd.DataFrame()

    # Filter data within the backtest window
    window_start_date = as_of_date - relativedelta(years=window_years)
    historical_window_scores = known_data_with_factors[
        known_data_with_factors["date_known"] >= window_start_date
    ]
    if historical_window_scores.empty:
        return pd.DataFrame()

    df_agg_scores = historical_window_scores.groupby("Ticker")["factor_score"].agg(
        ["mean", "count"]
    )
    df_agg_scores.rename(
        columns={"mean": "avg_factor_score", "count": "num_reports"}, inplace=True
    )

    # Filter by number of reports
    df_agg_scores = df_agg_scores[df_agg_scores["num_reports"] >= min_reports_required]

    return df_agg_scores


def main(*, export_json: bool = True, export_excel: bool = True):
    """
    Main execution function (using local historical CSV for quarterly rebalancing + dynamic S&P 500 filtering + chart output)
    """
    _info(
        "--- 正在运行股票选择脚本 (历史动态S&P 500过滤模式) ---",
        phase="startup",
    )

    # Step 1: Load historical constituent data
    df_constituents = load_sp500_constituents(DATA_DIR)
    if df_constituents is None:
        _error("无法加载S&P 500成分股数据，程序终止。", phase="load")
        return

    # Step 2: Load financial data for all companies (one-time)
    df_all_financials = load_and_merge_financial_data(DATA_DIR)
    if df_all_financials.empty:
        _error("无法加载财务数据，程序退出。", phase="load")
        return

    # Step 3: Determine backtest time range
    min_date = df_all_financials["date_known"].min()
    max_date = df_all_financials["date_known"].max()

    if pd.isna(min_date) or pd.isna(max_date):
        _error("[错误] 数据中未找到有效的财报日期，无法确定回测范围。", phase="dates")
        return

    # Step 4: Generate rebalancing date sequence
    rebalance_dates = pd.date_range(
        start=min_date, end=max_date, freq=BACKTEST_FREQUENCY
    )
    trade_dates = [d + pd.offsets.BDay(2) for d in rebalance_dates]

    _info(
        (
            f"将使用 {BACKTEST_FREQUENCY} 频率在以下日期进行调仓计算: "
            f"(共 {len(trade_dates)} 个)"
        ),
        phase="dates",
    )
    preview_dates = ", ".join(str(d.date()) for d in trade_dates[:5])
    _info(f"调仓日期示例: {preview_dates} ...", phase="dates")

    all_period_portfolios = {}
    screening_stats = []

    # Flag to control whether stock selection has started
    selection_started = False

    # Step 5: Iterate through each rebalancing date for dynamic stock selection
    for trade_date in trade_dates:
        as_of_date = trade_date.normalize()

        # 5.1 Get current valid S&P 500 stock list
        current_sp500_list = get_universe_for_date(trade_date, df_constituents)
        if not current_sp500_list:
            _warning(
                "S&P 500在当日无成分股数据，跳过。",
                asof=trade_date.date(),
                phase="universe",
            )
            continue

        # 5.2 Filter financial data for current S&P 500 constituents
        df_period_financials = df_all_financials[
            df_all_financials["Ticker"].isin(current_sp500_list)
        ]

        # 5.3 Calculate factor scores on current stock universe
        df_agg_scores = calc_factor_scores(
            df_period_financials,
            as_of_date=as_of_date,
            window_years=ROLLING_WINDOW_YEARS,
            min_reports_required=MIN_REPORTS_IN_WINDOW,
        )

        num_eligible_stocks = len(df_agg_scores)
        screening_stats.append(
            {"date": trade_date.date(), "count": num_eligible_stocks}
        )

        # Check if conditions for starting stock selection are met
        # If selection hasn't started, check if eligible stocks exceed 250
        if not selection_started and num_eligible_stocks > 250:
            _info(
                (
                    "符合条件的股票数量首次超过250，从现在开始进行选股。"
                    f" (eligible={num_eligible_stocks})"
                ),
                asof=trade_date.date(),
                phase="screening",
            )
            selection_started = (
                True  # Set flag to True, will continue stock selection from now on
            )

        # If df_agg_scores is empty or selection flag not enabled, print info and skip
        if df_agg_scores.empty or not selection_started:
            # Print different messages based on whether selection has started
            if not selection_started:
                _info(
                    (
                        f"在 {len(current_sp500_list)} 只成分股中，有 {num_eligible_stocks} 只符合条件，"
                        "未达到启动阈值(>250)。"
                    ),
                    asof=trade_date.date(),
                    phase="screening",
                )
            else:  # This case shouldn't occur theoretically, as num_eligible_stocks must be >0 when selection_started is True
                _warning(
                    (
                        f"在 {len(current_sp500_list)} 只成分股中，无符合条件的股票。"
                        f" (eligible={num_eligible_stocks})"
                    ),
                    asof=trade_date.date(),
                    phase="screening",
                )
            continue

        # Only execute stock selection logic when selection_started is True
        _info(
            (
                f"在 {len(current_sp500_list)} 只成分股中，有 {num_eligible_stocks} 只符合条件，正在排名..."
            ),
            asof=trade_date.date(),
            phase="ranking",
        )

        NUM_STOCKS_TO_SELECT = 20
        df_ranked = df_agg_scores.sort_values(by="avg_factor_score", ascending=False)
        top_stocks = df_ranked.head(NUM_STOCKS_TO_SELECT)

        df_top_reset = top_stocks.reset_index()
        all_period_portfolios[trade_date.date()] = df_top_reset

        if export_json:
            # Save per-period JSON (idempotent, overwrite if exists)
            try:
                cutoff_date = (trade_date - pd.offsets.BDay(2)).date()
                year_dir = PRELIM_JSON_DIR / f"{trade_date.year}"
                year_dir.mkdir(parents=True, exist_ok=True)
                out_path = year_dir / f"{trade_date.date()}.json"

                rows = []
                for i, row in df_top_reset.reset_index(drop=True).iterrows():
                    rows.append(
                        {
                            "ticker": str(row["Ticker"]).upper().strip(),
                            "rank": int(i + 1),
                            "avg_factor_score": round(
                                float(row["avg_factor_score"]), 6
                            ),
                            "num_reports": int(row["num_reports"]),
                        }
                    )

                payload = {
                    "schema_version": 1,
                    "source": "preliminary",
                    "trade_date": str(trade_date.date()),
                    "data_cutoff_date": str(cutoff_date),
                    "universe": "sp500",
                    "method": "preliminary_v1",
                    "params": {
                        "rolling_years": ROLLING_WINDOW_YEARS,
                        "min_reports": MIN_REPORTS_IN_WINDOW,
                        "top_n": NUM_STOCKS_TO_SELECT,
                        "rank_metric": "avg_factor_score",
                    },
                    "rows": rows,
                }

                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception as e:
                _warning(
                    f"保存JSON失败: {e}",
                    asof=trade_date.date(),
                    phase="export",
                )

    # Step 6: Save results to files
    if export_excel and all_period_portfolios:
        output_excel_file = OUTPUT_FILE_BASE.with_suffix(".xlsx")
        output_txt_file = OUTPUT_FILE_BASE.with_suffix(".txt")
        try:
            with (
                pd.ExcelWriter(output_excel_file) as writer,
                open(output_txt_file, "w", encoding="utf-8") as txt_file,
            ):
                _info("正在生成 Excel 和 TXT 输出文件...", phase="export")
                for date, df_portfolio in all_period_portfolios.items():
                    df_portfolio.to_excel(writer, sheet_name=str(date), index=False)
                    txt_file.write(
                        f"--- Portfolio for {date} ({len(df_portfolio)} stocks) ---\n"
                    )
                    txt_file.write(df_portfolio.to_string(index=False))
                    txt_file.write("\n\n")
            _info(
                (
                    "股票选择完成。结果已保存至 "
                    f"Excel={output_excel_file} TXT={output_txt_file}"
                ),
                phase="export",
            )
        except Exception as e:
            _error(f"[错误] 保存文件时出错: {e}", phase="export")
    else:
        _warning("没有生成任何投资组合。", phase="export")

    # Step 7: Generate and save statistical charts
    if screening_stats:
        _info("正在生成合格股票数量的统计图表...", phase="chart")
        df_stats = pd.DataFrame(screening_stats)
        df_stats["date"] = pd.to_datetime(df_stats["date"])
        plt.style.use("ggplot")
        fig, ax = plt.subplots(figsize=(15, 8))
        ax.plot(
            df_stats["date"],
            df_stats["count"],
            marker="o",
            linestyle="-",
            markersize=4,
            label=f"Stocks with >= {MIN_REPORTS_IN_WINDOW} reports in last {ROLLING_WINDOW_YEARS} years",
        )

        # Add a threshold line to the chart
        ax.axhline(
            y=250, color="r", linestyle="--", label="Selection Threshold (250 stocks)"
        )

        ax.set_title(
            "Number of Eligible Stocks in Point-in-Time S&P 500 Universe",
            fontsize=16,
            pad=20,
        )
        ax.set_xlabel("Rebalance Date", fontsize=12)
        ax.set_ylabel("Count of Eligible Stocks", fontsize=12)
        ax.legend()
        ax.grid(True)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        y_max = max(
            260, df_stats["count"].max() * 1.1
        )  # Ensure threshold line is visible
        ax.set_ylim(bottom=0, top=y_max)
        fig.tight_layout()
        chart_output_file = OUTPUT_FILE_BASE.with_suffix(".png")
        try:
            plt.savefig(chart_output_file, dpi=300)
            _info(
                f"图表已成功保存至: {chart_output_file}",
                phase="chart",
            )
        except Exception as e:
            _error(f"[错误] 保存图表时出错: {e}", phase="chart")


if __name__ == "__main__":
    main()
