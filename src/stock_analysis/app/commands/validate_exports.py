"""Validate exports command

Check consistency between Excel workbook and per-date JSON files.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.services.exports import validate_exports
from ...shared.logging import get_logger

logger = get_logger(__name__)


def run_validate_exports(
    source: str, excel: str | None = None, json_root: str | None = None
) -> int:
    try:
        ok = validate_exports(
            source,
            Path(excel) if excel else None,
            Path(json_root) if json_root else None,
        )
        if ok:
            logger.info("校验通过：Excel 与 JSON 完全一致")
            return 0
        else:
            logger.error("校验失败：存在不一致或缺失文件")
            return 2
    except Exception as e:
        logger.error(f"校验过程出错：{e}")
        return 1
