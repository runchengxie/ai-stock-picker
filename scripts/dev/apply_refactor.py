#!/usr/bin/env python3
"""Remove obsolete files before the final validation commit."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
shutil.rmtree(ROOT / "src/stock_analysis", ignore_errors=True)
(ROOT / ".github/workflows/refactor-validation.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
