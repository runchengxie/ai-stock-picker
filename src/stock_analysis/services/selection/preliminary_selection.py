"""Compatibility alias for research preliminary selection."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...research.selection import preliminary_selection as _impl

warn_legacy_import(
    "stock_analysis.services.selection.preliminary_selection",
    "stock_analysis.research.selection.preliminary_selection",
)
sys.modules[__name__] = _impl
