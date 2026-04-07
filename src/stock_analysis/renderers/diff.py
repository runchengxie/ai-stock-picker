"""Compatibility alias for the execution diff renderer."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.renderers import diff as _impl

warn_legacy_import(
    "stock_analysis.renderers.diff",
    "stock_analysis.execution.renderers.diff",
)
sys.modules[__name__] = _impl
