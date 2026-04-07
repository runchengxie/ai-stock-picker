"""Compatibility alias for AI-lab stock-picking services."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...ai_lab.selection import ai_stock_pick as _impl

warn_legacy_import(
    "stock_analysis.services.selection.ai_stock_pick",
    "stock_analysis.ai_lab.selection.ai_stock_pick",
)
sys.modules[__name__] = _impl
