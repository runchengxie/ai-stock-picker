"""LongPort quote command

Handles command logic for stock quote queries.
"""

from ...execution.renderers.table import render_quotes
from ...execution.services.account_snapshot import get_quotes
from ...shared.logging import get_logger
from .result import CommandResult

logger = get_logger(__name__)


def run_lb_quote(tickers: list[str]) -> CommandResult:
    """Run LongPort real-time quote query

    Args:
        tickers: List of stock symbols
        env: Environment selection (test or real)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        # Validate LongPort dependency early so tests can patch import
        __import__("stock_analysis.execution.broker.longport_client")

        logger.info(f"正在获取 {', '.join(tickers)} 的实时报价... (REAL)")

        # Get quote data
        quotes_dict = get_quotes(tickers)
        quotes_list = list(quotes_dict.values())

        # Render output
        output = render_quotes(quotes_list)

        return CommandResult(exit_code=0, stdout=output)

    except ImportError as e:
        logger.error(f"无法导入LongPort模块: {e}")
        logger.error("请确保已安装 longport 包：pip install longport")
        err = (
            "Error importing LongPort module: {msg}\n"
            "Please ensure the 'longport' package is installed: pip install "
            "longport"
        ).format(msg=e)
        return CommandResult(exit_code=1, stderr=err)
    except Exception as e:
        logger.error(f"获取报价失败：{e}")
        return CommandResult(exit_code=1)
