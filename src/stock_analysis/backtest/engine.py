"""Compatibility alias for the research backtest engine."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..research.backtest import engine as _impl

warn_legacy_import("stock_analysis.backtest.engine", "stock_analysis.research.backtest.engine")
sys.modules[__name__] = _impl
