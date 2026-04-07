"""Compatibility alias for research data-loading services."""

from __future__ import annotations

import sys

from ..._compat import warn_legacy_import
from ...research.data import load_data_to_db as _impl

warn_legacy_import(
    "stock_analysis.services.data.load_data_to_db",
    "stock_analysis.research.data.load_data_to_db",
)
sys.modules[__name__] = _impl
