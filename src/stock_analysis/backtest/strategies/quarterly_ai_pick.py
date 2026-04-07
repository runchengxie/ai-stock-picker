"""Compatibility alias for the AI-lab quarterly backtest strategy."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...ai_lab.backtest import quarterly_ai_pick as _impl

warn_legacy_import(
    "stock_analysis.backtest.strategies.quarterly_ai_pick",
    "stock_analysis.ai_lab.backtest.quarterly_ai_pick",
)
sys.modules[__name__] = _impl
