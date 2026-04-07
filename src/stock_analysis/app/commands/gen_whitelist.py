"""Generate ticker whitelist command.

Aggregates all tickers that appeared in preliminary or AI selection results
into a de-duplicated, uppercased, sorted list for price import filtering.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...shared.logging import get_logger
from ...shared.utils.paths import (
    AI_PORTFOLIO_FILE,
    OUTPUTS_DIR,
    QUANT_PORTFOLIO_FILE,
)

logger = get_logger(__name__)


def _clean_tickers(series: pd.Series) -> list[str]:
    return (
        series.astype("string")
        .str.upper()
        .str.strip()
        .dropna()
        .loc[lambda s: s != ""]
        .unique()
        .tolist()
    )


def _pick_ticker_column(df: pd.DataFrame) -> str | None:
    for name in ["Ticker", "ticker", "Symbol", "symbol"]:
        if name in df.columns:
            return name
    # Fall back to first column if it looks like tickers (heuristic: dtype object/string)
    if len(df.columns) > 0 and pd.api.types.is_object_dtype(df.dtypes.iloc[0]):
        return df.columns[0]
    return None


def _parse_date(s: str) -> pd.Timestamp | None:
    try:
        return pd.to_datetime(s, errors="raise")
    except Exception:
        return None


def run_gen_whitelist(
    source: str = "preliminary",
    excel_path: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    out_path: str | None = None,
) -> int:
    """Generate whitelist from selection spreadsheets.

    Args:
        source: "preliminary" or "ai"
        excel_path: Optional explicit path to the spreadsheet; otherwise uses defaults
        date_start: Inclusive start date (YYYY-MM-DD)
        date_end: Inclusive end date (YYYY-MM-DD)
        out_path: Output text file path
    """
    if source not in {"preliminary", "ai"}:
        logger.error("--from 仅支持 preliminary|ai")
        return 1

    default_excel = (
        QUANT_PORTFOLIO_FILE if source == "preliminary" else AI_PORTFOLIO_FILE
    )
    excel_file = Path(excel_path) if excel_path else default_excel

    if not excel_file.exists():
        logger.error(f"找不到结果文件: {excel_file}")
        return 1

    # Parse date window
    ds = pd.to_datetime(date_start) if date_start else None
    de = pd.to_datetime(date_end) if date_end else None

    # Read all sheets
    xls = pd.read_excel(excel_file, sheet_name=None, engine="openpyxl")

    tickers: set[str] = set()
    total_sheets = 0
    used_sheets = 0

    for sheet_name, df in xls.items():
        total_sheets += 1
        # Filter by date window if sheet name is a date
        include_sheet = True
        d = _parse_date(sheet_name)
        if d is not None and (ds is not None or de is not None):
            if ds is not None and d < ds:
                include_sheet = False
            if de is not None and d > de:
                include_sheet = False
        if not include_sheet:
            continue

        col = _pick_ticker_column(df)
        if not col:
            continue
        vals = _clean_tickers(df[col])
        if vals:
            tickers.update(vals)
            used_sheets += 1

    # Always include SPY for benchmark/backtest compatibility
    tickers.add("SPY")

    if not tickers:
        logger.error("未在指定时间窗内找到任何 Ticker。请检查输入文件与日期范围。")
        return 1

    # Sort and write
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = Path(out_path) if out_path else (OUTPUTS_DIR / "selected_tickers.txt")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        for t in sorted(tickers):
            f.write(f"{t}\n")

    logger.info(
        f"白名单已生成，共 {len(tickers)} 只，来自 {used_sheets}/{total_sheets} 个sheet：{out_file}"
    )
    return 0
