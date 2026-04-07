"""Backward-compatible exports for preliminary selection.

Older tests and scripts import ``stock_analysis.preliminary_selection``
directly. The implementation now lives under
``stock_analysis.research.selection.preliminary_selection``.
"""

from ._compat import warn_legacy_import
from .research.selection.preliminary_selection import *  # noqa: F403

warn_legacy_import(
    "stock_analysis.preliminary_selection",
    "stock_analysis.research.selection.preliminary_selection",
)
