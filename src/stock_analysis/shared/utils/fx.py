"""FX helpers

Lightweight helpers to convert broker-reported net assets into USD when the
base currency is non-USD, without hard network dependencies.

Priority of FX rate sources:
1) Environment variable: FX_<CCY>_USD (e.g., FX_HKD_USD=0.128)
   - Backward-compat: LONGPORT_FX_<CCY>_USD
2) Project config: config/config.yaml under fx.to_usd.{CCY} or fx.rates.{CCY}USD

If no rate is available, returns None and the caller should fallback to
valuation via USD cash + USD-quoted positions.
"""

from __future__ import annotations

import os

from ..config import load_cfg


def _from_env(ccy: str) -> float | None:
    key1 = f"FX_{ccy}_USD"
    key2 = f"LONGPORT_FX_{ccy}_USD"
    for k in (key1, key2):
        v = os.getenv(k)
        if v:
            try:
                return float(v)
            except Exception:
                return None
    return None


def _from_config(ccy: str) -> float | None:
    try:
        cfg = load_cfg() or {}
    except Exception:
        return None
    fx_cfg = (cfg.get("fx") or {}) if isinstance(cfg, dict) else {}
    # two possible shapes supported:
    # 1) fx: { to_usd: { HKD: 0.128 } }
    # 2) fx: { rates: { HKDUSD: 0.128 } }
    to_usd = fx_cfg.get("to_usd", {}) or {}
    if isinstance(to_usd, dict) and ccy in to_usd:
        try:
            return float(to_usd[ccy])
        except Exception:
            return None
    rates = fx_cfg.get("rates", {}) or {}
    key = f"{ccy}USD"
    if isinstance(rates, dict) and key in rates:
        try:
            return float(rates[key])
        except Exception:
            return None
    return None


def get_rate_to_usd(ccy: str) -> float | None:
    """Return FX rate for CCY->USD if available.

    ccy: Base currency code (e.g., "HKD").
    """
    c = (ccy or "").upper()
    if not c:
        return None
    if c == "USD":
        return 1.0
    return _from_env(c) or _from_config(c)


def to_usd(amount: float, ccy: str) -> float | None:
    """Convert amount from ccy into USD using available sources.

    Returns converted amount or None if no rate is available.
    """
    rate = get_rate_to_usd(ccy)
    if rate is None:
        return None
    try:
        return float(amount) * float(rate)
    except Exception:
        return None
