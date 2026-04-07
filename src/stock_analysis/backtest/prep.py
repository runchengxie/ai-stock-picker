"""Compatibility alias for research backtest data prep helpers."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..research.backtest import prep as _impl

warn_legacy_import("stock_analysis.backtest.prep", "stock_analysis.research.backtest.prep")
sys.modules[__name__] = _impl
