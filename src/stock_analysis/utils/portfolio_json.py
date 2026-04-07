"""Compatibility alias for canonical portfolio JSON helpers."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..contracts import portfolio_json as _impl

warn_legacy_import(
    "stock_analysis.utils.portfolio_json",
    "stock_analysis.contracts.portfolio_json",
)
sys.modules[__name__] = _impl
