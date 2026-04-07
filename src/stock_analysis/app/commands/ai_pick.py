"""AI stock picking command

Handles command logic for AI stock picking analysis.
"""

from ...shared.logging import get_logger

logger = get_logger(__name__)


def run_ai_pick(
    quarter: str | None = None,
    output: str | None = None,
    no_excel: bool = False,
    no_json: bool = False,
) -> int:
    """Run AI stock picking analysis

    Args:
        quarter: Specified quarter (optional)
        output: Output file path (optional)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        logger.info("正在运行AI选股分析...")

        if quarter:
            logger.info(f"指定季度：{quarter}")
        if output:
            logger.info(f"输出文件：{output}")

        from ...ai_lab.selection.ai_stock_pick import main as ai_pick_main

        export_excel = not no_excel
        export_json = not no_json
        ai_pick_main(export_json=export_json, export_excel=export_excel)

        logger.info("AI选股分析完成！")
        return 0

    except ImportError as e:
        logger.error(f"无法导入AI选股模块: {e}")
        return 1
    except Exception as e:
        logger.error(f"AI选股分析失败：{e}")
        return 1
