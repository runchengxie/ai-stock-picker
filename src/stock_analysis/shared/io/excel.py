"""Excel utility functions.

Provides utility functions for Excel file processing.
"""

import re
from pathlib import Path

import pandas as pd

from ..logging import get_logger

logger = get_logger(__name__)


def pick_latest_sheet(sheet_names: list[str]) -> str:
    """Select the latest quarter from sheet name list.

    Args:
        sheet_names: List of sheet names

    Returns:
        str: Latest sheet name
    """
    candidates = []

    for sheet_name in sheet_names:
        try:
            # Try to parse directly as date
            date = pd.to_datetime(sheet_name).date()
            candidates.append((date, sheet_name))
        except Exception:
            # Try to match yyyy-mm-dd format
            match = re.search(r"\d{4}-\d{2}-\d{2}", sheet_name)
            if match:
                try:
                    date = pd.to_datetime(match.group(0)).date()
                    candidates.append((date, sheet_name))
                except Exception:
                    continue

    if candidates:
        # Return the sheet with the latest date
        return max(candidates)[1]

    # Fallback: return the last sheet
    return sheet_names[-1] if sheet_names else ""


def read_latest_sheet_tickers(file_path: Path) -> tuple[list[str], str]:
    """Read stock ticker list from the latest sheet in Excel file.

    Args:
        file_path: Excel file path

    Returns:
        Tuple[List[str], str]: (ticker list, sheet name)

    Raises:
        FileNotFoundError: File does not exist
        ValueError: File format error or ticker column not found
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    try:
        # Read all sheets
        excel_file = pd.ExcelFile(file_path)

        # Select the latest sheet
        sheet_name = pick_latest_sheet(excel_file.sheet_names)
        logger.info(f"选择 sheet: {sheet_name}")

        # Read data
        df = pd.read_excel(excel_file, sheet_name=sheet_name)

        # Identify ticker column
        columns_lower = {col.lower(): col for col in df.columns}
        ticker_column = columns_lower.get("ticker") or columns_lower.get("symbol")

        if not ticker_column:
            raise ValueError("未找到 ticker 或 symbol 列")

        # Extract stock tickers
        tickers = (
            df[ticker_column].astype(str).str.upper().str.strip().dropna().tolist()
        )

        # Filter empty values
        tickers = [ticker for ticker in tickers if ticker and ticker != "NAN"]

        if not tickers:
            raise ValueError("未找到有效的股票代码")

        logger.info(f"成功读取 {len(tickers)} 个股票代码")
        return tickers, sheet_name

    except Exception as e:
        logger.error(f"读取 Excel 文件失败: {e}")
        raise


def read_excel_data(file_path: Path, sheet_name: str = None) -> pd.DataFrame:
    """Read Excel file data.

    Args:
        file_path: Excel file path
        sheet_name: Sheet name, reads first sheet if None

    Returns:
        pd.DataFrame: Excel data

    Raises:
        FileNotFoundError: File does not exist
        ValueError: File format error
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    try:
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path)

        logger.info(f"成功读取 Excel 文件，包含 {len(df)} 行数据")
        return df

    except Exception as e:
        logger.error(f"读取 Excel 文件失败: {e}")
        raise


def get_sheet_names(file_path: Path) -> list[str]:
    """Get all sheet names in Excel file.

    Args:
        file_path: Excel file path

    Returns:
        List[str]: List of sheet names

    Raises:
        FileNotFoundError: File does not exist
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    try:
        excel_file = pd.ExcelFile(file_path)
        return excel_file.sheet_names
    except Exception as e:
        logger.error(f"读取 Excel sheet 名称失败: {e}")
        raise
