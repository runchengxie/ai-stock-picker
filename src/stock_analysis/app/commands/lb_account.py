"""LongPort account command.

Handles command logic for account information queries while delegating
presentation to the CLI layer so that logging remains consistent.
"""

from ...execution.renderers.jsonout import render_multiple_account_snapshots_json
from ...execution.renderers.table import render_multiple_account_snapshots
from ...execution.services.account_snapshot import get_account_snapshot
from ...shared.logging import get_logger
from .result import CommandResult

logger = get_logger(__name__)


def run_lb_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
) -> CommandResult:
    """Run LongPort account overview

    Args:
        only_funds: Show only fund information
        only_positions: Show only position information
        fmt: Output format (table/json)

    Returns:
        int: Exit code (0 indicates success)
    """
    try:
        # Explicitly validate LongPort dependency early so tests can patch
        # import behavior without triggering SDK initialization.
        __import__("stock_analysis.execution.broker.longport_client")
        # Resolve conflicting flags: funds take precedence over positions
        if only_funds and only_positions:
            only_positions = False

        # Get real account snapshot
        snapshot = get_account_snapshot(env="real")
        snapshots = [snapshot]

        # Render output
        if fmt == "json":
            output = render_multiple_account_snapshots_json(snapshots)
        else:
            output = render_multiple_account_snapshots(
                snapshots, only_funds, only_positions
            )

        return CommandResult(exit_code=0, stdout=output)

    except ImportError as e:
        msg = f"Failed to import LongPort module: {e}"
        fix_msg = "Please ensure the 'longport' package is installed: pip install longport"
        logger.error(msg)
        logger.error(fix_msg)
        return CommandResult(exit_code=1, stderr="\n".join([msg, fix_msg]))
    except Exception as e:
        msg = f"Failed to get account overview: {e}"
        logger.error(msg)
        return CommandResult(exit_code=1, stderr=msg)
