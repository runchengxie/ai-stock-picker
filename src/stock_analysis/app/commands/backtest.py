"""Backtest command

Handles command logic for backtest analysis.
"""

import logging

from ...shared.logging import get_logger

logger = get_logger(__name__)


def _parse_log_level(level: str | None) -> int | None:
    if not level:
        return None
    m = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    return m.get(level.lower(), logging.INFO)


def run_backtest(
    strategy: str,
    config_path: str | None = None,
    *,
    target_percent: float | None = None,
    log_level: str | None = None,
) -> int:
    """Run backtest analysis

    Args:
        strategy: Strategy type ('ai', 'quant', 'spy', 'pe')
        config_path: Configuration file path (optional)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        logger.info(f"正在运行 {strategy.upper()} 策略回测...")

        lvl = _parse_log_level(log_level)

        if strategy == "ai":
            from ...ai_lab.backtest.quarterly_ai_pick import main as ai_main

            ai_main(log_level=lvl)
        elif strategy == "quant":
            from ...research.backtest.strategies.quarterly_unpicked import (
                main as quant_main,
            )

            quant_main(log_level=lvl)
        elif strategy == "spy":
            from ...research.backtest.strategies.benchmark_spy import main as spy_main

            spy_main(target_percent=target_percent, log_level=lvl)
        elif strategy == "pe":
            from ...research.backtest.strategies.pe_sector_alpha import main as pe_main

            pe_main()

        logger.info(f"{strategy.upper()} 策略回测完成！")
        return 0

    except ImportError as e:
        logger.error(f"无法导入回测模块: {e}")
        return 1
    except Exception as e:
        logger.error(f"回测执行失败：{e}")
        return 1
