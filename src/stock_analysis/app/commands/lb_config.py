"""LongPort configuration display command.

Reads effective configuration from environment variables and prints them.
Does not require importing the broker SDK or opening network connections.
"""

from __future__ import annotations

import os
from typing import Optional

from .result import CommandResult


def _getenv_both(name_new: str, name_old: str, default: Optional[str] = None) -> str:
    return os.getenv(name_new) or os.getenv(name_old) or (default or "")


def _to_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        return float(str(v)) if v is not None else default
    except Exception:
        return default


def _to_int(v: Optional[str], default: int = 0) -> int:
    try:
        return int(float(str(v))) if v is not None else default
    except Exception:
        return default


def _fmt_unlimited(val: float | int) -> str:
    try:
        if float(val) <= 0:
            return "Unlimited (0)"
    except Exception:
        return str(val)
    return f"{val}"


def run_lb_config(show: bool = True) -> CommandResult:
    """Print effective LongPort-related configuration from environment.

    Args:
        show: Whether to print the configuration (reserved for future flags)
    Returns:
        Exit code (0 success)
    """
    if not show:
        return CommandResult(exit_code=0)

    region = _getenv_both("LONGPORT_REGION", "LONGBRIDGE_REGION", "hk")
    overnight = _getenv_both("LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT", "false")

    max_notional = _getenv_both("LONGPORT_MAX_NOTIONAL_PER_ORDER", "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER", "0")
    max_qty = _getenv_both("LONGPORT_MAX_QTY_PER_ORDER", "LONGBRIDGE_MAX_QTY_PER_ORDER", "0")
    tw_start = _getenv_both("LONGPORT_TRADING_WINDOW_START", "LONGBRIDGE_TRADING_WINDOW_START", "09:30")
    tw_end = _getenv_both("LONGPORT_TRADING_WINDOW_END", "LONGBRIDGE_TRADING_WINDOW_END", "16:00")

    # Credentials presence (mask value)
    app_key = os.getenv("LONGPORT_APP_KEY") or os.getenv("LONGBRIDGE_APP_KEY")
    app_secret = os.getenv("LONGPORT_APP_SECRET") or os.getenv("LONGBRIDGE_APP_SECRET")
    token = os.getenv("LONGPORT_ACCESS_TOKEN") or os.getenv("LONGPORT_ACCESS_TOKEN_REAL")

    def _mask(s: Optional[str]) -> str:
        if not s:
            return "(not set)"
        if len(s) <= 6:
            return "***"
        return s[:3] + "***" + s[-3:]

    lines = [
        "LongPort Effective Configuration:",
        "- Region:        " + region,
        "- Overnight:     " + ("enabled" if _to_bool(overnight) else "disabled"),
        "- Max Notional:  " + _fmt_unlimited(_to_float(max_notional, 0.0)),
        "- Max Quantity:  " + _fmt_unlimited(_to_int(max_qty, 0)),
        "- Trade Window:  " + f"{tw_start} - {tw_end}",
        "- App Key:       " + _mask(app_key),
        "- App Secret:    " + _mask(app_secret),
        "- Access Token:  " + _mask(token),
    ]

    return CommandResult(exit_code=0, stdout="\n".join(lines))

