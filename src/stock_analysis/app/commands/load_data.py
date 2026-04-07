"""Data loading command

Handles command logic for data loading.
"""

from pathlib import Path

import pandas as pd

from ...shared.logging import get_logger

logger = get_logger(__name__)


def run_load_data(
    data_dir: str | None = None,
    skip_prices: bool = False,
    only_prices: bool = False,
    tickers_file: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> int:
    """Run data loading

    Args:
        data_dir: Data directory path (optional)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        logger.info("正在加载数据到数据库...")

        if data_dir:
            # If data directory is specified, need to temporarily modify path configuration
            logger.info(f"使用指定数据目录：{data_dir}")
            # Path configuration logic can be added here

        from ...research.data.load_data_to_db import main as load_main

        # Parse optional tickers whitelist
        wl: set[str] | None = None
        if tickers_file:
            path = Path(tickers_file)
            if not path.exists():
                logger.error(f"找不到 tickers 文件: {tickers_file}")
                return 1
            try:
                if path.suffix.lower() in {".xlsx", ".xls"}:
                    df = pd.read_excel(path)
                elif path.suffix.lower() == ".csv":
                    df = pd.read_csv(path)
                else:
                    # Treat as newline-delimited text file
                    with path.open("r", encoding="utf-8") as f:
                        wl = {
                            line.strip().upper()
                            for line in f
                            if line.strip() and not line.startswith("#")
                        }
                        logger.info(f"已从文本读取 {len(wl)} 个Ticker 白名单")
                    df = None

                if df is not None:
                    col = None
                    for name in ["Ticker", "ticker", "Symbol", "symbol"]:
                        if name in df.columns:
                            col = name
                            break
                    if col is None:
                        # Fall back to first column
                        col = df.columns[0]
                    wl = {str(t).upper().strip() for t in df[col].dropna().unique()}
                    logger.info(f"已从表格读取 {len(wl)} 个Ticker 白名单")
            except Exception as e:
                logger.error(f"解析 tickers 文件失败: {e}")
                return 1

        # Execute loading (supports importing only prices or skipping prices)
        load_main(
            skip_prices=skip_prices,
            only_prices=only_prices,
            tickers_whitelist=wl,
            date_start=date_start,
            date_end=date_end,
        )

        logger.info("数据加载完成！")
        return 0

    except ImportError as e:
        logger.error(f"无法导入数据加载模块: {e}")
        return 1
    except Exception as e:
        logger.error(f"数据加载失败：{e}")
        return 1
