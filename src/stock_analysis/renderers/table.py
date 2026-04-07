"""Compatibility alias for execution table renderers."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.renderers import table as _impl

warn_legacy_import("stock_analysis.renderers.table", "stock_analysis.execution.renderers.table")
sys.modules[__name__] = _impl

