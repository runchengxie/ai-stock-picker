"""Compatibility alias for the research SPY benchmark strategy."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...research.backtest.strategies import benchmark_spy as _impl

warn_legacy_import(
    "stock_analysis.backtest.strategies.benchmark_spy",
    "stock_analysis.research.backtest.strategies.benchmark_spy",
)
sys.modules[__name__] = _impl
