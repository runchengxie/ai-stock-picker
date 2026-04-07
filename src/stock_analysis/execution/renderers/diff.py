"""Diff-style renderer for rebalance previews."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ...shared.models import AccountSnapshot, Order, Position, RebalanceResult

_HAS_RICH = importlib.util.find_spec("rich") is not None


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:,.2f}%"


def _is_fund_symbol(symbol: str) -> bool:
    """Best-effort heuristic to classify fund-like symbols."""

    return "." not in symbol


@dataclass(slots=True)
class Buckets:
    cash: float
    stocks: float
    funds: float

    @property
    def total(self) -> float:
        return self.cash + self.stocks + self.funds


@dataclass(slots=True)
class RenderedRebalanceDiff:
    """Container with both plaintext and optional Rich renderables."""

    text: str
    rich: object | None = None


def _bucketize(snapshot: AccountSnapshot) -> Buckets:
    stocks_val = 0.0
    funds_val = 0.0
    for position in snapshot.positions:
        if _is_fund_symbol(position.symbol):
            funds_val += float(position.estimated_value)
        else:
            stocks_val += float(position.estimated_value)
    return Buckets(cash=float(snapshot.cash_usd), stocks=stocks_val, funds=funds_val)


def _bucketize_after(
    before_cash: float, targets: Iterable[Position], orders: Iterable[Order]
) -> tuple[Buckets, float]:
    notional_sell = 0.0
    notional_buy = 0.0
    for od in orders:
        px = float(od.price or 0.0)
        amt = px * float(od.quantity)
        if od.side.upper() == "SELL":
            notional_sell += amt
        else:
            notional_buy += amt
    total_fees = sum(float(getattr(order, "est_fees", 0.0) or 0.0) for order in orders)
    cash_after = float(before_cash) + notional_sell - notional_buy - total_fees

    stocks_val = 0.0
    funds_val = 0.0
    for target in targets:
        if _is_fund_symbol(target.symbol):
            funds_val += float(target.estimated_value)
        else:
            stocks_val += float(target.estimated_value)

    return Buckets(cash=cash_after, stocks=stocks_val, funds=funds_val), total_fees


def _diffstat(
    current: dict[str, Position], target: dict[str, Position]
) -> tuple[int, int, int, int]:
    added = 0
    removed = 0
    increased = 0
    decreased = 0
    all_symbols = set(current) | set(target)
    for symbol in sorted(all_symbols):
        cur_qty = int(current.get(symbol).quantity) if symbol in current else 0
        tgt_qty = int(target.get(symbol).quantity) if symbol in target else 0
        if cur_qty == 0 and tgt_qty > 0:
            added += 1
        elif cur_qty > 0 and tgt_qty == 0:
            removed += 1
        elif tgt_qty > cur_qty:
            increased += 1
        elif tgt_qty < cur_qty:
            decreased += 1
    return added, removed, increased, decreased


def render_rebalance_diff(
    result: RebalanceResult, before: AccountSnapshot
) -> RenderedRebalanceDiff:
    lines: list[str] = []

    buckets_before = _bucketize(before)
    buckets_after, total_fees = _bucketize_after(
        before.cash_usd, result.target_positions, result.orders
    )
    total_before = buckets_before.total
    total_after = (
        buckets_after.total if buckets_after.total > 0 else result.total_portfolio_value
    )

    mode = "DRY-RUN" if result.dry_run else "LIVE"

    lines.append("=== Rebalance Preview (Diff) ===")
    lines.append(f"As of: {before.env.upper()}  Currency: USD  Mode: {mode}")
    lines.append("--- Totals (Before → After) ---")

    summary_rows: list[tuple[str, float, float, float]] = []
    for label, before_value, after_value in (
        ("Cash", buckets_before.cash, buckets_after.cash),
        ("Stocks", buckets_before.stocks, buckets_after.stocks),
        ("Funds", buckets_before.funds, buckets_after.funds),
    ):
        delta_value = after_value - before_value
        summary_rows.append((label, before_value, after_value, delta_value))
        lines.append(
            f"{label:<6} {_fmt_money(before_value)} → {_fmt_money(after_value)}  "
            f"(Δ {_fmt_money(delta_value)})"
        )

    total_delta = total_after - total_before
    summary_rows.append(("Total", total_before, total_after, total_delta))
    lines.append(f"Total:  {_fmt_money(total_before)} → {_fmt_money(total_after)}")
    if total_fees and total_fees > 0:
        lines.append(f"Fees:   {_fmt_money(total_fees)}")
        lines.append(f"Cash After Fees: {_fmt_money(buckets_after.cash)}")
    lines.append("")

    current_map = {position.symbol: position for position in before.positions}
    target_map = {position.symbol: position for position in result.target_positions}
    diffstat = _diffstat(current_map, target_map)
    lines.append("--- Diffstat ---")
    lines.append(
        f"Added: {diffstat[0]}  Removed: {diffstat[1]}  "
        f"Increased: {diffstat[2]}  Decreased: {diffstat[3]}"
    )
    lines.append("")

    lines.append(
        "Symbol    Before(%)  Before($,sh)      →   After(%)   After($,sh)    "
        "Target(frac)  Rounded  Δfrac  Est.Fees  Action"
    )
    lines.append("-" * 90)

    denom_before = (
        total_before if total_before > 0 else max(1.0, result.total_portfolio_value)
    )
    denom_after = (
        total_after if total_after > 0 else max(1.0, result.total_portfolio_value)
    )

    positions_for_rich: list[dict[str, Any]] = []
    all_symbols = sorted(set(current_map) | set(target_map))
    for symbol in all_symbols:
        current = current_map.get(symbol)
        target = target_map.get(symbol)
        cur_val = float(current.estimated_value) if current else 0.0
        cur_qty = int(current.quantity) if current else 0
        tgt_val = float(target.estimated_value) if target else 0.0
        tgt_qty = int(target.quantity) if target else 0
        cur_weight = cur_val / denom_before if denom_before > 0 else 0.0
        tgt_weight = tgt_val / denom_after if denom_after > 0 else 0.0
        delta_qty = tgt_qty - cur_qty
        if delta_qty > 0:
            action = f"BUY {delta_qty}"
        elif delta_qty < 0:
            action = f"SELL {abs(delta_qty)}"
        else:
            action = "HOLD"

        related_orders = [
            order
            for order in result.orders
            if order.symbol.replace(".US", "") == symbol.replace(".US", "")
        ]
        first_order = related_orders[0] if related_orders else None
        target_frac = getattr(first_order, "target_qty_frac", None)
        rounded = getattr(first_order, "rounded_target_qty", None)
        rounding_loss = getattr(first_order, "rounding_loss", None)
        est_fee = getattr(first_order, "est_fees", None)

        target_frac_str = (
            f"{target_frac:.3f}" if isinstance(target_frac, float) else "   -   "
        )
        rounded_str = f"{rounded:d}" if isinstance(rounded, int) else " - "
        rounding_loss_str = (
            f"{rounding_loss:.3f}" if isinstance(rounding_loss, float) else "  -  "
        )
        fee_str = (
            _fmt_money(est_fee)
            if isinstance(est_fee, (int | float))
            else "$0.00"
        )
        lines.append(
            f"{symbol[:8]:8s}  {_fmt_pct(cur_weight):>8}  "
            f"{_fmt_money(cur_val):>12},{cur_qty:>4}  →  "
            f"{_fmt_pct(tgt_weight):>8}  {_fmt_money(tgt_val):>12},{tgt_qty:>4}  "
            f"{target_frac_str:>11}  {rounded_str:>7}  "
            f"{rounding_loss_str:>6}  {fee_str:>8}  {action}"
        )

        rounding_loss_val = (
            rounding_loss if isinstance(rounding_loss, float) else None
        )
        est_fee_val = (
            float(est_fee) if isinstance(est_fee, (int | float)) else 0.0
        )
        positions_for_rich.append(
            {
                "symbol": symbol,
                "cur_weight": cur_weight,
                "cur_val": cur_val,
                "cur_qty": cur_qty,
                "tgt_weight": tgt_weight,
                "tgt_val": tgt_val,
                "tgt_qty": tgt_qty,
                "target_frac": target_frac if isinstance(target_frac, float) else None,
                "rounded": rounded if isinstance(rounded, int) else None,
                "rounding_loss": rounding_loss_val,
                "est_fee": est_fee_val,
                "action": action,
            }
        )

    lines.append("")
    lines.append("--- Orders ---")

    orders_for_rich: list[dict[str, Any]] = []
    if not result.orders:
        lines.append("No orders (already aligned or below lot thresholds)")
    else:
        sell_first = sorted(
            result.orders,
            key=lambda order: (
                0 if order.side.upper() == "SELL" else 1,
                -(order.price or 0) * order.quantity,
            ),
        )
        for order in sell_first:
            est_amount = (order.price or 0.0) * float(order.quantity)
            price_display = "MKT" if not order.price else _fmt_money(order.price)
            order_line = (
                f"{order.side:4s} {order.symbol[:8]:8s} {order.quantity:>6} @ "
                f"{price_display:<8} est{_fmt_money(est_amount)}"
            )
            lines.append(order_line)
            orders_for_rich.append(
                {
                    "side": order.side,
                    "symbol": order.symbol,
                    "quantity": int(order.quantity),
                    "price_display": price_display,
                    "est_amount": est_amount,
                }
            )

    text_output = "\n".join(lines)
    rich_renderable = _build_rich_diff(
        env=before.env.upper(),
        mode=mode,
        currency="USD",
        summary_rows=summary_rows,
        diffstat=diffstat,
        positions=positions_for_rich,
        orders=orders_for_rich,
        fees=total_fees if total_fees and total_fees > 0 else 0.0,
        sheet_name=getattr(result, "sheet_name", None),
    )

    return RenderedRebalanceDiff(text=text_output, rich=rich_renderable)


def _build_rich_diff(
    *,
    env: str,
    mode: str,
    currency: str,
    summary_rows: list[tuple[str, float, float, float]],
    diffstat: tuple[int, int, int, int],
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    fees: float,
    sheet_name: str | None,
) -> object | None:
    if not _HAS_RICH:
        return None

    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    def _style_delta(value: float, text: str) -> str:
        if value > 0:
            return f"[green]{text}[/green]"
        if value < 0:
            return f"[red]{text}[/red]"
        return text

    def _signed_money(value: float) -> str:
        base = _fmt_money(abs(value))
        if value > 0:
            return f"+{base}"
        if value < 0:
            return f"-{base}"
        return base

    header_table = Table.grid(expand=True)
    header_table.add_column(justify="left")
    header_table.add_column(justify="right")
    header_table.add_row(f"[bold]{env} Account[/bold]", f"[bold]{mode}[/bold]")
    subtitle = f"Currency: {currency}"
    if sheet_name:
        header_table.add_row(f"Sheet: {sheet_name}", subtitle)
    else:
        header_table.add_row("", subtitle)

    summary_table = Table(
        title="Totals",
        show_header=True,
        header_style="bold",
        box=box.MINIMAL_DOUBLE_HEAD,
    )
    summary_table.add_column("Bucket")
    summary_table.add_column("Before", justify="right")
    summary_table.add_column("After", justify="right")
    summary_table.add_column("Δ", justify="right")
    for label, before_value, after_value, delta_value in summary_rows:
        summary_table.add_row(
            label,
            _fmt_money(before_value),
            _fmt_money(after_value),
            _style_delta(delta_value, _signed_money(delta_value)),
        )
    if fees:
        summary_table.add_row(
            "Fees",
            "-",
            _fmt_money(fees),
            _style_delta(-fees, _signed_money(-fees)),
        )

    diff_table = Table(
        title="Diffstat", show_header=True, header_style="bold", box=box.MINIMAL
    )
    diff_table.add_column("Metric")
    diff_table.add_column("Count", justify="right")
    for label, value in zip(
        ("Added", "Removed", "Increased", "Decreased"), diffstat, strict=True
    ):
        if label in {"Added", "Increased"}:
            styled = _style_delta(value, str(value))
        else:
            styled = _style_delta(-value, str(value))
        diff_table.add_row(label, styled)

    positions_table = Table(
        title="Per-position", show_header=True, header_style="bold", box=box.MINIMAL
    )
    positions_table.add_column("Symbol")
    positions_table.add_column("Before %", justify="right")
    positions_table.add_column("Before $", justify="right")
    positions_table.add_column("Before Qty", justify="right")
    positions_table.add_column("After %", justify="right")
    positions_table.add_column("After $", justify="right")
    positions_table.add_column("After Qty", justify="right")
    positions_table.add_column("Target frac", justify="right")
    positions_table.add_column("Rounded", justify="right")
    positions_table.add_column("Δ frac", justify="right")
    positions_table.add_column("Est. Fees", justify="right")
    positions_table.add_column("Action")

    for pos in positions:
        delta_frac = pos["rounding_loss"] or 0.0
        action = pos["action"]
        if action.startswith("BUY"):
            action = f"[green]{action}[/green]"
        elif action.startswith("SELL"):
            action = f"[red]{action}[/red]"
        positions_table.add_row(
            pos["symbol"],
            _fmt_pct(pos["cur_weight"]),
            _fmt_money(pos["cur_val"]),
            str(pos["cur_qty"]),
            _fmt_pct(pos["tgt_weight"]),
            _fmt_money(pos["tgt_val"]),
            str(pos["tgt_qty"]),
            f"{pos['target_frac']:.3f}" if pos["target_frac"] is not None else "-",
            str(pos["rounded"]) if pos["rounded"] is not None else "-",
            _style_delta(delta_frac, f"{delta_frac:.3f}")
            if pos["rounding_loss"] is not None
            else "-",
            _fmt_money(pos["est_fee"]),
            action,
        )

    orders_table = Table(
        title="Orders", show_header=True, header_style="bold", box=box.MINIMAL
    )
    orders_table.add_column("Side")
    orders_table.add_column("Symbol")
    orders_table.add_column("Qty", justify="right")
    orders_table.add_column("Price")
    orders_table.add_column("Est. Notional", justify="right")
    if not orders:
        orders_table.add_row("-", "(none)", "-", "-", "-")
    else:
        for order in orders:
            side = order["side"].upper()
            side_markup = f"[{'green' if side == 'BUY' else 'red'}]{order['side']}[/]"
            delta_value = order["est_amount"] if side == "BUY" else -order["est_amount"]
            orders_table.add_row(
                side_markup,
                order["symbol"],
                str(order["quantity"]),
                order["price_display"],
                _style_delta(delta_value, _signed_money(order["est_amount"])),
            )

    return Group(
        Panel(header_table, border_style="cyan"),
        summary_table,
        diff_table,
        positions_table,
        orders_table,
    )
