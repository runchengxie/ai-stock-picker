"""Portfolio JSON utilities.

Helpers to locate and read per-date JSON outputs for AI picks and
preliminary selections. Selection is based on the date encoded in the
filename (not modification time).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import json
import re

import pandas as pd

from ..shared.logging import get_logger
from ..shared.utils.paths import AI_PORTFOLIO_JSON_DIR, QUANT_PORTFOLIO_JSON_DIR

logger = get_logger(__name__)


_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")


def _iter_json_files(root: Path) -> Iterable[Path]:
    """Yield JSON files one level below year folders under root.

    Expected layout: root/YYYY/YYYY-MM-DD.json
    """
    if not root.exists():
        return []
    for year_dir in sorted(root.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for fp in year_dir.glob("*.json"):
            if fp.is_file():
                yield fp


def _parse_date_from_filename(fp: Path) -> Optional[pd.Timestamp]:
    name = fp.stem  # e.g., 2025-09-05
    m = _DATE_RE.match(name)
    if not m:
        return None
    try:
        return pd.to_datetime(m.group(1))
    except Exception:
        return None


@dataclass
class PortfolioTickers:
    tickers: list[str]
    asof: str


def pick_latest_result_json(root: Path) -> Optional[Path]:
    """Pick the latest result JSON by filename date, not mtime."""

    candidates: list[tuple[pd.Timestamp, Path]] = []
    for fp in _iter_json_files(root):
        ts = _parse_date_from_filename(fp)
        if ts is not None:
            candidates.append((ts, fp))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def read_result_json_tickers(fp: Path) -> PortfolioTickers:
    """Read strategy result JSON and return tickers plus asof date.

    Supports both AI outputs (`picks`) and preliminary outputs (`rows`).
    """
    if not fp.exists():
        raise FileNotFoundError(f"文件不存在: {fp}")

    raw = json.loads(fp.read_text(encoding="utf-8"))
    items = raw.get("picks")
    if items is None:
        items = raw.get("rows") or []
    tickers = [str(x.get("ticker", "")).upper().strip() for x in items if x]
    tickers = [t for t in tickers if t]
    asof = str(raw.get("trade_date") or fp.stem)
    if not tickers:
        raise ValueError(f"JSON中未找到有效的ticker列表：{fp}")
    return PortfolioTickers(tickers=tickers, asof=asof)


def find_result_json_for_date(asof: str, root: Path) -> Optional[Path]:
    """Find the result JSON for a given date (YYYY-MM-DD) by filename."""

    try:
        y = asof[:4]
    except Exception:
        y = ""
    if y.isdigit():
        candidate = root / y / f"{asof}.json"
        if candidate.exists():
            return candidate

    for fp in _iter_json_files(root):
        if fp.stem == asof:
            return fp
    return None


def find_ai_json_for_date(asof: str, root: Path | None = None) -> Optional[Path]:
    """Find the AI pick JSON for a given date (YYYY-MM-DD) by filename.

    Searches year subfolder first, then all files under root for a name match.
    """
    base = root or AI_PORTFOLIO_JSON_DIR
    return find_result_json_for_date(asof, base)


def pick_latest_ai_json(root: Path | None = None) -> Optional[Path]:
    """Pick the latest AI pick JSON by filename date, not mtime."""

    return pick_latest_result_json(root or AI_PORTFOLIO_JSON_DIR)


def read_ai_json_tickers(fp: Path) -> PortfolioTickers:
    """Backward-compatible wrapper for AI result JSON readers."""

    return read_result_json_tickers(fp)


def pick_latest_preliminary_json(root: Path | None = None) -> Optional[Path]:
    """Pick the latest preliminary result JSON by filename date."""

    return pick_latest_result_json(root or QUANT_PORTFOLIO_JSON_DIR)


def read_preliminary_json_tickers(fp: Path) -> PortfolioTickers:
    """Read preliminary result JSON and return tickers plus asof date."""

    return read_result_json_tickers(fp)


def find_preliminary_json_for_date(asof: str, root: Path | None = None) -> Optional[Path]:
    """Find the preliminary JSON for a given date (YYYY-MM-DD)."""

    return find_result_json_for_date(asof, root or QUANT_PORTFOLIO_JSON_DIR)
