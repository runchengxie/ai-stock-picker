"""Compatibility alias for the research quarterly point-in-time strategy."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...research.backtest.strategies import quarterly_unpicked as _impl

warn_legacy_import(
    "stock_analysis.backtest.strategies.quarterly_unpicked",
    "stock_analysis.research.backtest.strategies.quarterly_unpicked",
)
sys.modules[__name__] = _impl
