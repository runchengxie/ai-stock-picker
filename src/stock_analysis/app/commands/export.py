"""Export command

Bridge Excel <-> per-period JSON exports for preliminary and AI pick flows.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.services.exports import export_excel_to_json, export_json_to_excel
from ...shared.logging import get_logger

logger = get_logger(__name__)


def run_export(
    source: str,
    direction: str,
    overwrite: bool = False,
    excel: str | None = None,
    json_root: str | None = None,
) -> int:
    try:
        logger.info(
            f"正在导出（source={source}, direction={direction}, overwrite={overwrite})..."
        )
        if direction == "excel-to-json":
            written = export_excel_to_json(
                source,
                Path(excel) if excel else None,
                Path(json_root) if json_root else None,
                overwrite,
            )
            logger.info(f"导出完成：写入 {written} 个JSON文件")
            return 0
        else:
            sheets = export_json_to_excel(
                source,
                Path(json_root) if json_root else None,
                Path(excel) if excel else None,
            )
            logger.info(f"导出完成：写入 {sheets} 个工作表")
            return 0
    except Exception as e:
        logger.error(f"导出失败：{e}")
        return 1
