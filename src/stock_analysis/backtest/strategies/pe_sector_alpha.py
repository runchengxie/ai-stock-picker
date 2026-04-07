"""Compatibility alias for the research PE-sector alpha strategy."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...research.backtest.strategies import pe_sector_alpha as _impl

warn_legacy_import(
    "stock_analysis.backtest.strategies.pe_sector_alpha",
    "stock_analysis.research.backtest.strategies.pe_sector_alpha",
)
sys.modules[__name__] = _impl
