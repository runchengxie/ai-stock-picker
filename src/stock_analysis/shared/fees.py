from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeeSchedule:
    commission: float = 0.0
    platform_per_share: float = 0.005
    fractional_pct_lt1: float = 0.012
    fractional_cap_lt1: float = 0.99
    sell_reg_fees_bps: float = 0.0


def estimate_fees(
    side: str,
    qty_int: int,
    price: float,
    *,
    any_fractional_lt1: bool,
    fs: FeeSchedule,
) -> tuple[float, float]:
    """Estimate fees for Phase 1 (integer execution).

    Returns (est_fee, frac_hint):
    - est_fee: commission + platform + sell-side reg (integer shares only)
    - frac_hint: if target fractional <1 share, a hint cost for awareness (not booked)
    """
    notional = max(qty_int, 0) * max(price, 0.0)
    commission = float(fs.commission or 0.0)
    platform = float(fs.platform_per_share or 0.0) * max(qty_int, 0)
    reg = 0.0
    if (side or "").upper() == "SELL" and (fs.sell_reg_fees_bps or 0.0) > 0:
        reg = float(fs.sell_reg_fees_bps) / 10000.0 * notional

    frac_hint = 0.0
    if any_fractional_lt1:
        # Hint: cost if one were to trade <1 share fractionally
        # min(% of $1 notional, capped per order)
        one_share_notional = max(price, 0.0)
        frac_hint = min(
            float(fs.fractional_pct_lt1 or 0.0) * one_share_notional,
            float(fs.fractional_cap_lt1 or 0.0),
        )

    return float(commission + platform + reg), float(frac_hint)
