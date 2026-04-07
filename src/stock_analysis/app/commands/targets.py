"""Targets command

Generate and manage live rebalance target files (JSON), decoupled from
backtest AI pick outputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd

from ...shared.logging import get_logger
from ...shared.utils.paths import (
    AI_PORTFOLIO_FILE,
    AI_PORTFOLIO_JSON_DIR,
    OUTPUTS_DIR,
    QUANT_PORTFOLIO_FILE,
    QUANT_PORTFOLIO_JSON_DIR,
)
from ...contracts.targets import write_targets_json
from ...shared.io.excel import (
    get_sheet_names,
    pick_latest_sheet,
    read_excel_data,
)
from ...contracts.portfolio_json import (
    find_result_json_for_date,
    pick_latest_result_json,
    read_result_json_tickers,
)

logger = get_logger(__name__)


def _extract_tickers_from_df(df: pd.DataFrame) -> list[str]:
    cols = {str(c).lower(): str(c) for c in df.columns}
    col = cols.get("ticker") or cols.get("symbol")
    if not col:
        raise ValueError("未找到 ticker 或 symbol 列")
    vals = (
        df[col].astype(str).str.upper().str.strip().dropna().tolist()
        if not df.empty
        else []
    )
    return [v for v in vals if v and v != "NAN"]


def _latest_sheet_and_tickers(xlsx: Path) -> Tuple[str, list[str]]:
    sheet = pick_latest_sheet(get_sheet_names(xlsx))
    df = read_excel_data(xlsx, sheet_name=sheet)
    tickers = _extract_tickers_from_df(df)
    return sheet, tickers


def _source_defaults(source: str) -> tuple[Path, Path, str, str]:
    if source == "preliminary":
        return (
            QUANT_PORTFOLIO_FILE,
            QUANT_PORTFOLIO_JSON_DIR,
            "research",
            "初筛",
        )
    return AI_PORTFOLIO_FILE, AI_PORTFOLIO_JSON_DIR, "ai_lab", "AI Lab"


def run_targets_gen(
    source: str = "ai",
    excel: str | None = None,
    out: str | None = None,
    asof: str | None = None,
) -> int:
    """Generate canonical schema-v2 targets from AI/research artifacts."""
    try:
        default_excel, json_root, target_source, source_label = _source_defaults(source)

        # 1) JSON-first normalization path for both AI and research outputs
        if excel is None:
            json_fp: Path | None
            if asof:
                json_fp = find_result_json_for_date(asof, json_root)
                if not json_fp:
                    json_fp = None
            else:
                json_fp = pick_latest_result_json(json_root)

            if json_fp:
                data = read_result_json_tickers(json_fp)
                tickers = data.tickers
                asof_date = data.asof

                if not tickers:
                    logger.error("未找到有效的股票代码")
                    return 1

                out_path = (
                    Path(out) if out else (OUTPUTS_DIR / "targets" / f"{asof_date}.json")
                )
                write_targets_json(
                    out_path,
                    tickers=tickers,
                    asof=asof_date,
                    source=target_source,
                )
                logger.info(
                    "已生成 schema v2 调仓目标: %s JSON -> %s（%d 只）",
                    source_label,
                    out_path,
                    len(tickers),
                )
                return 0

        # 2) Excel fallback (explicit or migration path when JSON is absent)
        xlsx = Path(excel) if excel else default_excel
        if not xlsx.exists():
            logger.error(
                "%s 结果文件不存在: %s。请先生成 JSON/Excel 结果后再运行 targets gen。",
                source_label,
                xlsx,
            )
            return 1

        if asof:
            df = read_excel_data(xlsx, sheet_name=asof)
            tickers = _extract_tickers_from_df(df)
            sheet = asof
        else:
            sheet, tickers = _latest_sheet_and_tickers(xlsx)

        if not tickers:
            logger.error("未找到有效的股票代码")
            return 1

        out_path = Path(out) if out else (OUTPUTS_DIR / "targets" / f"{sheet}.json")
        write_targets_json(
            out_path,
            tickers=tickers,
            asof=sheet,
            source=target_source,
        )
        logger.info("已从 %s Excel 归一化 schema v2 调仓目标: %s", source_label, out_path)
        return 0
    except Exception as e:
        logger.error(f"生成调仓目标失败：{e}")
        return 1
