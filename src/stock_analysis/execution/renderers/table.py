"""Table renderer

Provides table format data rendering functionality.
"""

from ...shared.models import AccountSnapshot, Order, Quote, RebalanceResult


def render_quotes(quotes: list[Quote]) -> str:
    """Render stock quotes table

    Args:
        quotes: List of quotes

    Returns:
        str: Formatted table string
    """
    if not quotes:
        return "No quote data"

    lines = []
    lines.append("Real-time quotes:")
    lines.append("-" * 50)

    for quote in quotes:
        lines.append(
            f"{quote.symbol:12} | Price: {quote.price:>10.2f} | Time: {quote.timestamp}"
        )

    return "\n".join(lines)


def render_account_snapshot(
    snapshot: AccountSnapshot, only_funds: bool = False, only_positions: bool = False
) -> str:
    """Render account snapshot table

    Args:
        snapshot: Account snapshot
        only_funds: Only show fund information
        only_positions: Only show position information

    Returns:
        str: Formatted table string
    """
    lines = []

    # Environment identifier
    if snapshot.env == "real":
        lines.append("!!! REAL ACCOUNT DATA (READ-ONLY) !!!")

    # Fund information
    if not only_positions:
        lines.append(f"\n[{snapshot.env.upper()}] Cash (USD): ${snapshot.cash_usd:,.2f}")
        if not only_funds:
            lines.append(f"Positions value: ${snapshot.total_market_value:,.2f}")
            lines.append(f"Total assets: ${snapshot.total_portfolio_value:,.2f}")

    # Position information
    if not only_funds:
        if snapshot.positions:
            if not only_positions:
                lines.append("\nPositions:")
            lines.append("Symbol        Qty        Last       Est.Value")
            lines.append("-" * 50)

            for position in snapshot.positions:
                lines.append(
                    f"{position.symbol:12} {position.quantity:10} "
                    f"{position.last_price:10.2f} ${position.estimated_value:>10,.2f}"
                )
        else:
            if not only_positions:
                lines.append("\nNo positions held")

    return "\n".join(lines)


def render_multiple_account_snapshots(
    snapshots: list[AccountSnapshot],
    only_funds: bool = False,
    only_positions: bool = False,
) -> str:
    """Render multiple account snapshots

    Args:
        snapshots: List of account snapshots
        only_funds: Only show fund information
        only_positions: Only show position information

    Returns:
        str: Formatted table string
    """
    if not snapshots:
        return "No account data"

    lines = []
    for snapshot in snapshots:
        lines.append(render_account_snapshot(snapshot, only_funds, only_positions))

    return "\n".join(lines)


def render_rebalance_plan(result: RebalanceResult) -> str:
    """Render rebalance plan table

    Args:
        result: Rebalance result

    Returns:
        str: Formatted table string
    """
    lines = []

    # Title
    mode = "Dry Run" if result.dry_run else "Execution Mode"
    lines.append(f"\n=== {mode} - {result.sheet_name} Rebalance Summary ===")
    lines.append("-" * 80)

    # Account overview
    lines.append(f"Total assets: ${result.total_portfolio_value:,.2f}")
    lines.append(
        f"Equal weight allocation: target value per stock ${result.target_value_per_stock:,.2f}"
    )
    lines.append("-" * 80)

    # Rebalance details header
    lines.append("Symbol   | Last Price | Current Qty | Target Qty | Delta   | Action")
    lines.append("-" * 80)

    # Build current positions mapping
    current_positions_map = {pos.symbol: pos for pos in result.current_positions}

    # Show rebalance situation for each target stock
    for target_pos in result.target_positions:
        current_pos = current_positions_map.get(target_pos.symbol)
        current_qty = current_pos.quantity if current_pos else 0

        delta_qty = target_pos.quantity - current_qty

        # Find corresponding order
        order = None
        for o in result.orders:
            if o.symbol == target_pos.symbol or o.symbol.replace(
                ".US", ""
            ) == target_pos.symbol.replace(".US", ""):
                order = o
                break

        if order:
            action = f"{order.side} {order.quantity}"
        elif abs(delta_qty) > 0:
            action = "Skip (too small delta)"
        else:
            action = "No change"

        lines.append(
            f"{target_pos.symbol[:8]:8s} | {target_pos.last_price:8.2f} | "
            f"{current_qty:8d} | {target_pos.quantity:8d} | {delta_qty:7d} | {action}"
        )

    # Order summary
    lines.append(f"\nProcessed {len(result.orders)} orders")

    if result.dry_run:
        lines.append("\nNote: this is a dry run, no orders were placed")
        lines.append("Use --execute to place real orders")
    else:
        lines.append("\nWarning: orders have been placed, please check your brokerage account")

    return "\n".join(lines)


def render_orders(orders: list[Order]) -> str:
    """Render order list

    Args:
        orders: List of orders

    Returns:
        str: Formatted table string
    """
    if not orders:
        return "No order data"

    lines = []
    lines.append("Order details:")
    lines.append("Symbol   | Side | Qty    | Price    | Status   | Order ID")
    lines.append("-" * 65)

    for order in orders:
        price_str = f"{order.price:.2f}" if order.price else "MARKET"
        order_id_str = order.order_id[:8] if order.order_id else "N/A"

        lines.append(
            f"{order.symbol[:8]:8s} | {order.side:4s} | {order.quantity:6d} | "
            f"{price_str:8s} | {order.status:8s} | {order_id_str}"
        )

        if order.error_message:
            lines.append(f"  -> Error: {order.error_message}")

    return "\n".join(lines)
