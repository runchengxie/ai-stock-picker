"""Quantitative preliminary screening command

Handles command logic for quantitative preliminary stock screening.
"""

from ...shared.logging import get_logger

logger = get_logger(__name__)


def run_preliminary(
    output_dir: str | None = None,
    no_excel: bool = False,
    no_json: bool = False,
) -> int:
    """Run quantitative preliminary stock screening

    Args:
        output_dir: Output directory path (optional)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        logger.info("正在运行量化初筛选股...")

        if output_dir:
            logger.info(f"输出目录：{output_dir}")
            # Output directory configuration logic can be added here

        from ...research.selection.preliminary_selection import main as prelim_main

        export_excel = not no_excel
        export_json = not no_json
        prelim_main(export_json=export_json, export_excel=export_excel)

        logger.info("量化初筛选股完成！")
        return 0

    except ImportError as e:
        logger.error(f"无法导入量化初筛模块: {e}")
        return 1
    except Exception as e:
        logger.error(f"量化初筛选股失败：{e}")
        return 1
