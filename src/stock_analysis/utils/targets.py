"""Compatibility alias for canonical target contracts."""

from __future__ import annotations

import sys

from .._compat import warn_legacy_import
from ..contracts import targets as _impl

warn_legacy_import("stock_analysis.utils.targets", "stock_analysis.contracts.targets")
sys.modules[__name__] = _impl
