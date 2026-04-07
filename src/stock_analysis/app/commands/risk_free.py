"""CLI helpers for managing cached risk-free rates."""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Iterable

from ...shared.config import get_risk_free_settings
from ...shared.logging import get_logger
from ...shared.services.marketdata import (
    RiskFreeCacheInfo,
    RiskFreeRateService,
    RiskFreeRateServiceError,
)
from ...shared.utils.paths import DB_PATH
from .result import CommandResult

logger = get_logger(__name__)

_DATE_FMT = "%Y-%m-%d"
_DEFAULT_WINDOW_DAYS = 365 * 5


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, _DATE_FMT).date()
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise argparse.ArgumentTypeError(f"Invalid date: {value}") from exc


def _format_cache_info(info: RiskFreeCacheInfo) -> str:
    start = info.start_date.isoformat() if info.start_date else "-"
    end = info.end_date.isoformat() if info.end_date else "-"
    updated = info.last_updated.isoformat() if info.last_updated else "-"
    return (
        f"Series:        {info.series}\n"
        f"Cached rows:   {info.rows}\n"
        f"Coverage:      {start} → {end}\n"
        f"Last refreshed: {updated}"
    )


def _format_rows(rows: Iterable[tuple[str, float]]) -> str:
    lines = ["date        rate"]
    for date_str, rate in rows:
        lines.append(f"{date_str:10s}  {rate: .6f}")
    return "\n".join(lines)


def run_risk_free(args: argparse.Namespace) -> CommandResult:
    """Entrypoint for ``stockq rf`` command group."""

    settings = get_risk_free_settings()
    service = RiskFreeRateService.from_app_config(settings=settings, db_path=DB_PATH)

    ttl_override = getattr(args, "ttl_days", None)
    if ttl_override is not None:
        ttl_value = int(ttl_override)
        if ttl_value < 0:
            return CommandResult(1, stderr="ttl-days must be >= 0")
        service.ttl_days = ttl_value

    series_id = getattr(args, "series", None) or service.default_series
    sub = getattr(args, "rf_command", None)

    try:
        if sub == "update":
            return _run_update(service, series_id, args)
        if sub == "show":
            return _run_show(service, series_id, args)
        if sub == "purge":
            return _run_purge(service, series_id)
        # Default to info when no subcommand is provided
        return _run_info(service, series_id)
    except RiskFreeRateServiceError as exc:
        logger.error("Risk-free operation failed: %s", exc)
        return CommandResult(1, stderr=str(exc))


def _run_update(
    service: RiskFreeRateService,
    series_id: str,
    args: argparse.Namespace,
) -> CommandResult:
    today = dt.date.today()
    info_before = service.describe_cache(series_id)

    start = _parse_date(getattr(args, "start", None)) or info_before.start_date
    end = _parse_date(getattr(args, "end", None)) or today

    if start is None:
        start = today - dt.timedelta(days=_DEFAULT_WINDOW_DAYS)
    if end < start:
        return CommandResult(1, stderr="end date must be on or after start date")

    refreshed = service.ensure_range(start, end, series=series_id, force=getattr(args, "force", False))
    inserted = max(0, refreshed.rows - info_before.rows)
    message = (
        f"Updated cache for {series_id}.\n"
        f"Fetched range: {start.isoformat()} → {end.isoformat()}\n"
        f"New rows added: {inserted}\n"
        f"Coverage now:  {refreshed.start_date or '-'} → {refreshed.end_date or '-'}"
    )
    return CommandResult(0, stdout=message)


def _run_show(
    service: RiskFreeRateService,
    series_id: str,
    args: argparse.Namespace,
) -> CommandResult:
    limit = getattr(args, "limit", 10) or 10
    if limit <= 0:
        return CommandResult(1, stderr="limit must be positive")
    df = service.fetch_recent(limit=limit, series=series_id)
    if df.empty:
        return CommandResult(0, stdout="No cached observations found.")
    rows = list(zip(df["date"].dt.strftime(_DATE_FMT), df["rate"].astype(float)))
    return CommandResult(0, stdout=_format_rows(rows))


def _run_purge(service: RiskFreeRateService, series_id: str) -> CommandResult:
    service.purge(series=series_id)
    return CommandResult(0, stdout=f"Cleared cached data for {series_id}.")


def _run_info(service: RiskFreeRateService, series_id: str) -> CommandResult:
    info = service.describe_cache(series=series_id)
    return CommandResult(0, stdout=_format_cache_info(info))


__all__ = ["run_risk_free"]
