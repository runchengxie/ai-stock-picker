"""LongPort rebalance command.

Consumes canonical target JSON files and turns them into live or dry-run
rebalance plans.
"""

from pathlib import Path

from ...contracts.targets import read_targets_json
from ...execution.renderers.diff import render_rebalance_diff
from ...shared.logging import get_logger
from .result import CommandResult

logger = get_logger(__name__)


def run_lb_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    env: str = "real",
    target_gross_exposure: float = 1.0,
) -> CommandResult:
    """Run LongPort differential rebalancing.

    Based on real account snapshot, calculate the difference between target positions and current holdings, execute rebalancing operations.
    Regardless of test or real environment, follow a unified path: first get account snapshot, calculate differences, then decide whether to place real orders.

    Args:
        input_file: Canonical targets JSON file path
        account: Account name
        dry_run: Whether it's dry run mode
        env: Environment selection (test or real)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        # Validate LongPort dependency early so tests can patch import
        __import__("stock_analysis.execution.broker.longport_client")
        # Force use REAL environment; without --execute it's dry run preview
        env = "real"
        if dry_run:
            logger.info("模式: 干跑模式（真实账户快照，预览不下单）")
        else:
            logger.warning("模式: 实盘执行（真实下单，谨慎操作）")

        logger.info(f"正在读取 canonical target 文件: {input_file}")
        logger.info(f"账户: {account}")
        logger.info(f"环境: {env.upper()}")

        # Check if file exists
        file_path = Path(input_file)
        if not file_path.exists():
            msg = f"File not found: {input_file}"
            logger.error(msg)
            return CommandResult(exit_code=1, stderr=msg)

        if file_path.suffix.lower() != ".json":
            msg = (
                "Legacy workbook inputs are deprecated for live execution. "
                "Generate a canonical schema-v2 target file with "
                "'stockq targets gen --from ai|preliminary' and rerun "
                "'stockq lb-rebalance <targets.json>'."
            )
            logger.error(msg)
            return CommandResult(exit_code=1, stderr=msg)

        # Import heavy dependencies lazily after basic validation
        from ...execution.services.account_snapshot import (
            get_account_snapshot,
            get_quotes,
        )
        from ...execution.services.rebalancer import RebalanceService

        # Read canonical target file
        try:
            tg = read_targets_json(file_path, require_schema_v2=True)
            sheet_name = tg.asof or file_path.stem
            logger.info(
                "成功读取 canonical targets JSON: %s（asof=%s），包含 %d 条目标",
                file_path.name,
                sheet_name,
                len(tg.targets),
            )
        except Exception as e:
            logger.error(f"读取输入文件失败：{e}")
            return CommandResult(exit_code=1, stderr=str(e))

        # Build single client throughout the process to avoid repeated initialization causing multiple permission table prints
        from ...execution.broker.longport_client import LongPortClient

        client = LongPortClient(env=env)
        # Get account snapshot (without quotes, will fetch all at once later)
        account_snapshot = get_account_snapshot(
            env=env, include_quotes=False, client=client
        )

        # Fetch quotes all at once: target stocks + existing positions
        from ...execution.broker.longport_client import _to_lb_symbol

        target_syms = {
            _to_lb_symbol(target.symbol, market=target.market) for target in tg.targets
        }
        held_syms = {p.symbol for p in account_snapshot.positions}
        all_syms = target_syms | held_syms
        if all_syms:
            quote_objs = get_quotes(list(all_syms), client=client)
            quote_map = {k: v.price for k, v in quote_objs.items()}
        else:
            quote_map = {}

        # Use unified quotes to backfill position valuations in account snapshot, avoid Before being 0
        if quote_map and account_snapshot.positions:
            for pos in account_snapshot.positions:
                px = float(quote_map.get(pos.symbol, pos.last_price or 0.0) or 0.0)
                if px > 0:
                    pos.last_price = px
                    pos.estimated_value = float(px) * float(pos.quantity)
            # Synchronously update snapshot totals, if total assets were 0 before, fall back to cash + position valuations
            total_mv = sum(float(p.estimated_value) for p in account_snapshot.positions)
            account_snapshot.total_market_value = total_mv
            if not account_snapshot.total_portfolio_value:
                account_snapshot.total_portfolio_value = (
                    float(account_snapshot.cash_usd) + total_mv
                )

        # Initialize rebalance service
        rebalance_service = RebalanceService(env=env, client=client)

        try:
            effective_exposure = tg.target_gross_exposure
            if target_gross_exposure != 1.0 and tg.target_gross_exposure == 1.0:
                effective_exposure = target_gross_exposure

            # 制定调仓计划
            rebalance_result = rebalance_service.plan_rebalance(
                tg.targets,
                account_snapshot,
                quotes=quote_map,
                target_gross_exposure=effective_exposure,
            )
            rebalance_result.dry_run = dry_run
            rebalance_result.sheet_name = sheet_name
            rebalance_result.target_source = tg.source
            rebalance_result.target_asof = tg.asof or sheet_name
            rebalance_result.target_input_path = str(file_path)

            # 执行订单
            executed_orders = rebalance_service.execute_orders(
                rebalance_result.orders, dry_run
            )
            rebalance_result.orders = executed_orders

            # 保存审计日志
            log_file = rebalance_service.save_audit_log(rebalance_result, dry_run)

            # 渲染输出：优先展示 Diff 视图，更直观地体现“调仓前后对比 + 订单”
            diff_view = render_rebalance_diff(rebalance_result, account_snapshot)

            logger.info(f"审计日志已保存到: {log_file}")

            return CommandResult(
                exit_code=0,
                stdout=diff_view.text,
                rich_renderable=diff_view.rich,
            )

        finally:
            rebalance_service.close()

    except ImportError as e:
        # Standardized error reporting to stderr to aid tests and UX
        logger.error(f"无法导入必要模块: {e}")
        err = (
            "Failed to import LongPort module: {msg}\n"
            "Please ensure the 'longport' package is installed: pip install "
            "longport"
        ).format(msg=e)
        return CommandResult(exit_code=1, stderr=err)
    except Exception as e:
        logger.error(f"仓位调整失败：{e}")
        return CommandResult(exit_code=1)
