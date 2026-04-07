"""Compatibility alias for execution JSON renderers."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..execution.renderers import jsonout as _impl

warn_legacy_import(
    "stock_analysis.renderers.jsonout",
    "stock_analysis.execution.renderers.jsonout",
)
sys.modules[__name__] = _impl
