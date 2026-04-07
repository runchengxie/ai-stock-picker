"""Command line interface module.

Responsible only for argument parsing and command dispatching, without business logic.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import uuid
from typing import TYPE_CHECKING, Any

from .commands.ai_pick import run_ai_pick
from .commands.backtest import run_backtest
from .commands.load_data import run_load_data as _run_load_data
from .commands.result import CommandResult
from ..shared.logging import get_logger, set_run_id

if TYPE_CHECKING:
    from rich.console import Console

_RICH_AVAILABLE = importlib.util.find_spec("rich") is not None
_RICH_CONSOLE: Console | None = None

if _RICH_AVAILABLE:
    from rich.console import Console
    from rich.traceback import install as install_rich_traceback

    _RICH_CONSOLE = Console()
    install_rich_traceback(show_locals=False)


# Internal store for passing parsed options to thin wrappers
_LOAD_DATA_OPTS: dict[str, Any] | None = None


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser.

    Returns:
        argparse.ArgumentParser: Configured argument parser
    """
    parser = argparse.ArgumentParser(
        prog="stockq",
        description=(
            "Stock Quantitative Analysis Tool - 以 research 主线、ai-lab 实验流和 "
            "execution 平台边界组织的量化研究与调仓工具"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  [research]
  stockq load-data
  stockq preliminary
  stockq backtest quant

  [ai-lab / experimental]
  stockq ai-pick
  stockq backtest ai

  [execution]
  stockq targets gen --from ai
  stockq lb-account --format json
  stockq lb-rebalance outputs/targets/2025-09-05.json
  stockq lb-rebalance outputs/targets/2025-09-05.json --execute
        """,
    )

    # Add version information
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    # Create subcommands
    subparsers = parser.add_subparsers(
        dest="command", help="可用的命令", metavar="COMMAND"
    )
    parser._subparsers_action = subparsers  # type: ignore[attr-defined]

    # Backtest command
    backtest_parser = subparsers.add_parser(
        "backtest", help="运行回测分析", description="运行不同策略的回测分析"
    )
    backtest_parser.add_argument(
        "strategy",
        choices=["ai", "quant", "pe", "spy"],
        help="回测策略类型：ai(实验性AI选股), quant(主线量化初选), pe(PE估值因子), spy(SPY基准)",
    )
    backtest_parser.add_argument("--config", type=str, help="配置文件路径（可选）")
    backtest_parser.add_argument(
        "--target",
        type=float,
        help="买入并持有的目标仓位比例（仅对 spy 有效，如 0.99）",
    )
    backtest_parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error", "critical"],
        help="回测日志级别（影响分红与再平衡日志粒度）",
    )

    # Data loading command
    load_parser = subparsers.add_parser(
        "load-data",
        help="加载数据到数据库",
        description="从CSV文件加载财务数据和价格数据到SQLite数据库",
    )
    load_parser.add_argument(
        "--data-dir", type=str, help="数据目录路径（可选，默认使用项目data目录）"
    )
    load_parser.add_argument(
        "--tickers-file",
        type=str,
        help="仅导入此清单中的股价（支持 .txt/.csv/.xlsx；文本按行一个ticker）",
    )
    load_parser.add_argument(
        "--date-start",
        type=str,
        help="价格导入起始日期（YYYY-MM-DD，可选）",
    )
    load_parser.add_argument(
        "--date-end",
        type=str,
        help="价格导入结束日期（YYYY-MM-DD，可选）",
    )
    group = load_parser.add_mutually_exclusive_group()
    group.add_argument(
        "--skip-prices",
        action="store_true",
        help="跳过股价数据导入（仅导入财报类表）",
    )
    group.add_argument(
        "--only-prices",
        action="store_true",
        help="仅导入股价数据（跳过财报类表）",
    )

    # Preliminary screening command
    prelim_parser = subparsers.add_parser(
        "preliminary",
        help="运行量化初筛选股",
        description="执行多因子量化初筛，生成候选股票池",
    )
    prelim_parser.add_argument(
        "--output-dir", type=str, help="输出目录路径（可选，默认使用项目outputs目录）"
    )
    prelim_parser.add_argument(
        "--no-excel", action="store_true", help="仅生成JSON，不写Excel/TXT"
    )
    prelim_parser.add_argument(
        "--no-json", action="store_true", help="仅生成Excel/TXT，不写JSON"
    )

    # AI stock picking command
    ai_parser = subparsers.add_parser(
        "ai-pick",
        help="运行实验性AI选股分析",
        description="使用AI模型进行实验性股票筛选和分析（ai-lab workflow）",
    )
    ai_parser.add_argument(
        "--quarter", type=str, help="指定季度（格式：YYYY-QX，如2024-Q1）"
    )
    ai_parser.add_argument("--output", type=str, help="输出文件路径（可选）")
    ai_parser.add_argument(
        "--no-excel", action="store_true", help="仅生成JSON，不写Excel"
    )
    ai_parser.add_argument(
        "--no-json", action="store_true", help="仅生成Excel，不写JSON"
    )

    # Risk-free rate management command
    rf_parser = subparsers.add_parser(
        "rf",
        help="管理无风险利率缓存",
        description="更新与检查无风险利率（FRED）缓存",
    )
    rf_parser.add_argument(
        "--series",
        type=str,
        help="FRED 序列 ID（默认读取配置中的 series）",
    )
    rf_parser.add_argument(
        "--ttl-days",
        type=int,
        help="覆盖配置中的缓存刷新天数（单位：天）",
    )
    rf_sub = rf_parser.add_subparsers(dest="rf_command", metavar="SUBCOMMAND")
    rf_sub.add_parser("info", help="显示缓存状态（默认子命令）")
    rf_update = rf_sub.add_parser(
        "update",
        help="抓取并缓存指定时间范围内的无风险利率",
    )
    rf_update.add_argument("--start", type=str, help="起始日期 YYYY-MM-DD")
    rf_update.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD")
    rf_update.add_argument(
        "--force",
        action="store_true",
        help="忽略 TTL 限制并强制刷新",
    )
    rf_show = rf_sub.add_parser("show", help="查看最近的缓存记录")
    rf_show.add_argument(
        "--limit",
        type=int,
        default=10,
        help="显示最近N条记录（默认10）",
    )
    rf_sub.add_parser("purge", help="清除当前序列的缓存")

    # Export command
    export_parser = subparsers.add_parser(
        "export",
        help="导出Excel/JSON",
        description="在Excel与分期JSON之间进行双向导出",
    )
    export_parser.add_argument(
        "--from",
        dest="source",
        choices=["preliminary", "ai"],
        default="preliminary",
        help="数据来源：preliminary 或 ai",
    )
    export_parser.add_argument(
        "--direction",
        choices=["excel-to-json", "json-to-excel"],
        default="excel-to-json",
        help="导出方向（默认 excel-to-json）",
    )
    export_parser.add_argument(
        "--excel", type=str, help="指定Excel路径（可选，默认读取/写入项目既定路径）"
    )
    export_parser.add_argument(
        "--json-root", type=str, help="指定JSON根目录（可选，默认在outputs下）"
    )
    export_parser.add_argument(
        "--overwrite", action="store_true", help="excel->json 时覆盖已存在文件"
    )

    # Validate exports command
    validate_parser = subparsers.add_parser(
        "validate-exports",
        help="校验Excel与JSON一致性",
        description="检查同一调仓日在Excel与JSON中的股票集合是否一致",
    )
    validate_parser.add_argument(
        "--source",
        choices=["preliminary", "ai"],
        default="preliminary",
        help="数据来源：preliminary 或 ai",
    )
    validate_parser.add_argument("--excel", type=str, help="Excel路径（可选）")
    validate_parser.add_argument("--json-root", type=str, help="JSON根目录（可选）")

    # Generate whitelist command
    gen_parser = subparsers.add_parser(
        "gen-whitelist",
        help="从结果文件生成Ticker白名单",
        description="汇总 preliminary 或 AI 结果中的全部Ticker，去重并输出白名单文件",
    )
    gen_parser.add_argument(
        "--from",
        dest="source",
        choices=["preliminary", "ai"],
        default="preliminary",
        help="读取哪类结果文件（默认：preliminary）",
    )
    gen_parser.add_argument(
        "--excel",
        type=str,
        help=(
            "结果Excel路径（默认：outputs/point_in_time_backtest_quarterly_sp500_historical.xlsx 或 "  # noqa: E501
            "outputs/point_in_time_ai_stock_picks_all_sheets.xlsx）"
        ),
    )
    gen_parser.add_argument(
        "--date-start", type=str, help="起始日期（YYYY-MM-DD，可选）"
    )
    gen_parser.add_argument("--date-end", type=str, help="结束日期（YYYY-MM-DD，可选）")
    gen_parser.add_argument(
        "--out",
        type=str,
        help="输出白名单路径（默认：outputs/selected_tickers.txt）",
    )

    # LongPort quote command
    lb_quote_parser = subparsers.add_parser(
        "lb-quote",
        help="获取LongPort实时报价",
        description="通过LongPort API获取指定股票的实时报价",
    )
    lb_quote_parser.add_argument(
        "tickers", nargs="+", help="股票代码列表（如 AAPL MSFT 700.HK）"
    )

    # LongPort rebalance command
    lb_rebalance_parser = subparsers.add_parser(
        "lb-rebalance",
        help="根据目标组合调整仓位",
        description=(
            "读取 canonical schema-v2 targets JSON，生成仓位调整订单（默认干跑模式）"
        ),
    )
    lb_rebalance_parser.add_argument(
        "input_file",
        type=str,
        help=(
            "目标输入文件：canonical targets JSON（如 outputs/targets/2025-09-05.json）"
        ),
    )
    lb_rebalance_parser.add_argument(
        "--account", type=str, default="main", help="账户名称（默认：main）"
    )
    lb_rebalance_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="干跑模式，只打印不实际下单（默认开启）",
    )
    lb_rebalance_parser.add_argument(
        "--execute", action="store_true", help="实际执行交易（关闭干跑模式）"
    )
    lb_rebalance_parser.add_argument(
        "--target-gross-exposure",
        type=float,
        default=1.0,
        help="目标总敞口比例覆盖值（当 targets.json 未显式给出时使用，默认 1.0）",
    )

    # No longer expose env, default to real; --execute controls actual order execution

    # LongPort account overview command
    lb_account_parser = subparsers.add_parser(
        "lb-account",
        help="查看 LongPort 真实账户概览",
        description="展示真实账户的资金与持仓",
    )
    lb_account_parser.add_argument("--funds", action="store_true", help="只看资金")
    lb_account_parser.add_argument("--positions", action="store_true", help="只看持仓")
    lb_account_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式：table 表格 / json JSON格式",
    )

    # LongPort configuration display
    lb_cfg_parser = subparsers.add_parser(
        "lb-config",
        help="显示 LongPort 相关环境配置",
        description="读取环境变量并显示LongPort区域、隔夜、下单上限与交易时段等配置",
    )
    lb_cfg_parser.add_argument(
        "--show",
        action="store_true",
        default=True,
        help="显示配置（默认）",
    )

    # Targets command group
    targets_parser = subparsers.add_parser(
        "targets",
        help="生成与管理实盘调仓目标（targets JSON）",
        description=(
            "将 research 或 ai-lab 结果归一化为 canonical schema-v2 调仓目标 JSON"
        ),
    )
    targets_sub = targets_parser.add_subparsers(dest="targets_cmd", metavar="SUB")
    t_gen = targets_sub.add_parser(
        "gen",
        help="从AI/初筛结果生成targets JSON",
        description=(
            "默认优先读取最新 research/ai-lab JSON 结果并归一化为 schema-v2 targets；"  # noqa: E501
            "如显式提供 --excel 则从旧版 Excel 结果迁移生成"
        ),
    )
    t_gen.add_argument(
        "--from",
        dest="source",
        choices=["ai", "preliminary"],
        default="ai",
        help="来源：ai(实验性 ai-lab) 或 preliminary(research)（默认：ai）",
    )
    t_gen.add_argument(
        "--excel",
        type=str,
        help=(
            "可选：显式指定来源Excel（默认：AI总表 outputs/point_in_time_ai_stock_picks_all_sheets.xlsx）"  # noqa: E501
        ),
    )
    t_gen.add_argument(
        "--asof",
        type=str,
        help="可选：指定sheet日期（YYYY-MM-DD）；默认取最新sheet",
    )
    t_gen.add_argument(
        "--out",
        type=str,
        help="可选：输出路径（默认：outputs/targets/{asof}.json）",
    )

    return parser


def _handle_command_result(result: int | CommandResult) -> int:
    """Normalize command results to an exit code while emitting output."""

    if isinstance(result, CommandResult):
        if _RICH_CONSOLE is not None and result.rich_renderable is not None:
            _RICH_CONSOLE.print(result.rich_renderable)
            if result.stdout:
                _RICH_CONSOLE.print()
        if result.stdout:
            if _RICH_CONSOLE is not None:
                _RICH_CONSOLE.print(result.stdout, highlight=False)
            else:
                print(result.stdout)
        return result.exit_code
    return int(result)


def main() -> int:
    """Main entry function.

    Responsible only for argument parsing and command dispatching.

    Returns:
        int: Exit code (0 indicates success)
    """
    run_id = uuid.uuid4().hex[:12]
    set_run_id(run_id)
    logger = get_logger(__name__)

    parser = create_parser()
    try:
        args = parser.parse_args()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code != 0 and len(sys.argv) > 1:
            logger.error("Unknown command: %s", sys.argv[1])
            return 1
        return code

    # Show help if no command is provided
    if not args.command:
        parser.print_help()
        return 0

    # Dispatch to corresponding handler function based on command
    try:
        if args.command == "backtest":
            kwargs: dict[str, object] = {}
            if args.target is not None:
                kwargs["target_percent"] = args.target
            if args.log_level is not None:
                kwargs["log_level"] = args.log_level
            return _handle_command_result(
                run_backtest(args.strategy, getattr(args, "config", None), **kwargs)
            )
        elif args.command == "load-data":
            # Record options for the thin wrapper and call with a single arg
            global _LOAD_DATA_OPTS
            _LOAD_DATA_OPTS = {
                "skip_prices": getattr(args, "skip_prices", False),
                "only_prices": getattr(args, "only_prices", False),
                "tickers_file": getattr(args, "tickers_file", None),
                "date_start": getattr(args, "date_start", None),
                "date_end": getattr(args, "date_end", None),
            }
            return _handle_command_result(
                run_load_data(getattr(args, "data_dir", None))
            )
        elif args.command == "preliminary":
            from .commands.preliminary import run_preliminary

            return _handle_command_result(
                run_preliminary(
                    getattr(args, "output_dir", None),
                    getattr(args, "no_excel", False),
                    getattr(args, "no_json", False),
                )
            )
        elif args.command == "ai-pick":
            return _handle_command_result(
                run_ai_pick(
                    getattr(args, "quarter", None),
                    getattr(args, "output", None),
                )
            )
        elif args.command == "rf":
            from .commands.risk_free import run_risk_free

            return _handle_command_result(run_risk_free(args))
        elif args.command == "export":
            from .commands.export import run_export

            return _handle_command_result(
                run_export(
                    getattr(args, "source", "preliminary"),
                    getattr(args, "direction", "excel-to-json"),
                    getattr(args, "overwrite", False),
                    getattr(args, "excel", None),
                    getattr(args, "json_root", None),
                )
            )
        elif args.command == "validate-exports":
            from .commands.validate_exports import run_validate_exports

            return _handle_command_result(
                run_validate_exports(
                    getattr(args, "source", "preliminary"),
                    getattr(args, "excel", None),
                    getattr(args, "json_root", None),
                )
            )
        elif args.command == "gen-whitelist":
            from .commands.gen_whitelist import run_gen_whitelist

            return _handle_command_result(
                run_gen_whitelist(
                    getattr(args, "source", "preliminary"),
                    getattr(args, "excel", None),
                    getattr(args, "date_start", None),
                    getattr(args, "date_end", None),
                    getattr(args, "out", None),
                )
            )
        elif args.command == "lb-quote":
            return _handle_command_result(run_lb_quote(args.tickers))
        elif args.command == "lb-rebalance":
            # If --execute is specified, disable dry-run mode
            dry_run = not getattr(args, "execute", False)
            return _handle_command_result(
                run_lb_rebalance(
                    args.input_file,
                    getattr(args, "account", "main"),
                    dry_run,
                    "real",
                    getattr(args, "target_gross_exposure", 1.0),
                )
            )
        elif args.command == "lb-account":
            return _handle_command_result(
                run_lb_account(
                    only_funds=getattr(args, "funds", False),
                    only_positions=getattr(args, "positions", False),
                    fmt=getattr(args, "format", "table"),
                )
            )
        elif args.command == "lb-config":
            return _handle_command_result(run_lb_config(getattr(args, "show", True)))
        elif args.command == "targets":
            from .commands.targets import run_targets_gen

            sub = getattr(args, "targets_cmd", None)
            if sub == "gen":
                return _handle_command_result(
                    run_targets_gen(
                        source=getattr(args, "source", "ai"),
                        excel=getattr(args, "excel", None),
                        out=getattr(args, "out", None),
                        asof=getattr(args, "asof", None),
                    )
                )
            else:
                parser.print_help()
                return 0
        else:
            logger.error("Unknown command: %s", args.command)
            return 1
    except ImportError as e:
        logger.error(f"无法导入命令模块: {e}")
        return 1


def run_lb_quote(tickers: list[str]) -> int:  # type: ignore[override]
    """Forwarder for lb_quote to support test patching and lazy import."""
    from .commands.lb_quote import run_lb_quote as _run_lb_quote

    return _handle_command_result(_run_lb_quote(tickers))


def run_lb_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    env: str = "real",
    target_gross_exposure: float = 1.0,
) -> int:  # type: ignore[override]
    """Forwarder for lb_rebalance to support test patching and lazy import."""
    from .commands.lb_rebalance import run_lb_rebalance as _run_lb_rebalance

    return _handle_command_result(
        _run_lb_rebalance(
            input_file,
            account,
            dry_run,
            env,
            target_gross_exposure,
        )
    )


def run_lb_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
) -> int:  # type: ignore[override]
    """Forwarder for lb_account with lazy import."""
    try:
        from .commands.lb_account import run_lb_account as _run_lb_account
    except ImportError:
        logger = get_logger(__name__)
        logger.error(
            "Failed to import LongPort module. Please install it via 'pip install "
            "longport'"
        )
        return 1

    return _handle_command_result(
        _run_lb_account(
            only_funds=only_funds,
            only_positions=only_positions,
            fmt=fmt,
        )
    )


def run_lb_config(show: bool = True) -> int:  # type: ignore[override]
    """Forwarder for lb_config with lazy import."""
    from .commands.lb_config import run_lb_config as _run_lb_config

    return _handle_command_result(_run_lb_config(show))


def run_load_data(data_dir: str | None = None) -> int:  # type: ignore[override]
    """Thin wrapper to satisfy tests while preserving full options.

    The tests patch `stock_analysis.app.cli.run_load_data` and expect it to be
    called with a single argument. We still forward all parsed options captured
    in `_LOAD_DATA_OPTS` to the real implementation.
    """
    from pathlib import Path

    opts = _LOAD_DATA_OPTS or {}
    # Validate data_dir only at the CLI boundary so tests that call the
    # underlying implementation directly can mock internals freely.
    if data_dir:
        dpath = Path(data_dir)
        if not dpath.exists() or not dpath.is_dir():
            from ..shared.logging import get_logger

            get_logger(__name__).error(f"指定的数据目录不存在或不是目录：{data_dir}")
            return 1
    return _run_load_data(
        data_dir,
        skip_prices=bool(opts.get("skip_prices", False)),
        only_prices=bool(opts.get("only_prices", False)),
        tickers_file=opts.get("tickers_file"),
        date_start=opts.get("date_start"),
        date_end=opts.get("date_end"),
    )


def app() -> None:
    """Application entry point for the ``stockq`` console script.

    The entry point is defined after the helper forwarders so that when this
    module is executed as ``python -m stock_analysis.cli``, all required
    functions are already bound before :func:`main` dispatches to them.
    """

    sys.exit(main())


if __name__ == "__main__":
    app()
