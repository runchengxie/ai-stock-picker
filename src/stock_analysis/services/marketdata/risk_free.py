"""Risk-free rate retrieval and caching helpers."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from ...config import RiskFreeSettings, get_risk_free_settings
from ...logging import get_logger
from ...utils.paths import DB_PATH

LOGGER = get_logger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_PADDING_DAYS = 7
_TRADING_DAYS_PER_YEAR = 252


def _utc_now() -> dt.datetime:
    """Return a timezone-aware UTC timestamp."""

    return dt.datetime.now(dt.UTC)


class RiskFreeRateServiceError(RuntimeError):
    """Base exception for risk-free service errors."""


class RiskFreeRateFetchError(RiskFreeRateServiceError):
    """Raised when risk-free data cannot be fetched from the remote source."""


@dataclass(frozen=True)
class RiskFreeCacheInfo:
    """Summary of cached risk-free data."""

    series: str
    start_date: dt.date | None
    end_date: dt.date | None
    rows: int
    last_updated: dt.datetime | None


class RiskFreeRateService:
    """Service responsible for fetching, caching and serving risk-free rates."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        default_series: str = "DGS3MO",
        ttl_days: int | None = 5,
        fallback_rate: float | None = None,
        padding_days: int = _DEFAULT_PADDING_DAYS,
        session: requests.Session | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_series = default_series
        self.ttl_days = ttl_days
        self.fallback_rate = fallback_rate
        self.padding_days = max(0, int(padding_days))
        self.session = session or requests.Session()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_app_config(
        cls,
        *,
        settings: RiskFreeSettings | None = None,
        db_path: Path = DB_PATH,
    ) -> "RiskFreeRateService":
        """Build a service instance using project configuration."""

        cfg = settings or get_risk_free_settings()
        return cls(
            db_path=db_path,
            default_series=cfg.series,
            ttl_days=cfg.ttl_days,
            fallback_rate=cfg.fallback_rate,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ensure_range(
        self,
        start_date: dt.date,
        end_date: dt.date,
        *,
        series: str | None = None,
        force: bool = False,
    ) -> RiskFreeCacheInfo:
        """Ensure cache covers the requested date range."""

        start = self._normalize_date(start_date)
        end = self._normalize_date(end_date)
        if start > end:
            raise RiskFreeRateServiceError("start_date must be before end_date")

        series_id = series or self.default_series
        with self._connect() as conn:
            self._ensure_tables(conn)
            info = self._get_cache_info(conn, series_id)
            if force or self._needs_refresh(info, start, end):
                try:
                    self._refresh_range(conn, series_id, start, end)
                except RiskFreeRateServiceError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive guard
                    raise RiskFreeRateServiceError(str(exc)) from exc
                info = self._get_cache_info(conn, series_id)
        return info

    def get_series_for_index(
        self,
        index: pd.DatetimeIndex,
        *,
        series: str | None = None,
        force_refresh: bool = False,
    ) -> pd.Series:
        """Return daily risk-free rates aligned to ``index``."""

        if not isinstance(index, pd.DatetimeIndex):
            raise TypeError("index must be a pandas.DatetimeIndex")
        if index.empty:
            return pd.Series(dtype=float)

        normalized_index = pd.DatetimeIndex(index).tz_localize(None)
        start = normalized_index.min().date()
        end = normalized_index.max().date()

        series_id = series or self.default_series

        try:
            self.ensure_range(start, end, series=series, force=force_refresh)
        except RiskFreeRateServiceError as exc:
            if self.fallback_rate is not None:
                LOGGER.warning(
                    "Falling back to constant risk-free rate %.6f due to error: %s",
                    self.fallback_rate,
                    exc,
                )
                return pd.Series(self.fallback_rate, index=normalized_index, dtype=float)
            raise RiskFreeRateServiceError(
                f"{exc}. Run 'stockq rf update --start {start.isoformat()} --end {end.isoformat()}'"
                f" to populate {series_id} data."
            ) from exc

        with self._connect() as conn:
            query = (
                "SELECT date, rate FROM risk_free_rates "
                "WHERE series=? AND date BETWEEN ? AND ? ORDER BY date"
            )
            rows = conn.execute(
                query,
                (
                    series_id,
                    start.isoformat(),
                    end.isoformat(),
                ),
            ).fetchall()

        if not rows:
            if self.fallback_rate is not None:
                LOGGER.warning(
                    "No risk-free observations in cache for %s; using fallback %.6f",
                    series_id,
                    self.fallback_rate,
                )
                return pd.Series(self.fallback_rate, index=normalized_index, dtype=float)
            raise RiskFreeRateServiceError(
                "No cached risk-free data for series "
                f"{series_id} between {start} and {end}. "
                f"Run 'stockq rf update --start {start.isoformat()} --end {end.isoformat()}'"
                " to fetch the missing observations."
            )

        df = pd.DataFrame(rows, columns=["date", "rate"])
        df["date"] = pd.to_datetime(df["date"], utc=False)
        daily = df.set_index("date")["rate"].sort_index()
        aligned = daily.reindex(normalized_index).ffill().bfill()
        return aligned.astype(float)

    def compute_sharpe(
        self,
        returns: pd.Series,
        *,
        series: str | None = None,
        periods: int = _TRADING_DAYS_PER_YEAR,
    ) -> float | None:
        """Compute annualized Sharpe ratio using cached risk-free data."""

        if not isinstance(returns, pd.Series):
            raise TypeError("returns must be a pandas.Series")
        if returns.empty:
            return None

        returns_index = pd.DatetimeIndex(returns.index).tz_localize(None)
        rf_daily = self.get_series_for_index(returns_index, series=series)
        aligned_returns = returns.astype(float)
        aligned_rf = rf_daily.reindex(returns_index).ffill().bfill()
        excess = aligned_returns - aligned_rf
        excess = excess.dropna()
        if excess.empty:
            return None

        sigma = excess.std(ddof=1)
        if sigma is None or sigma == 0 or pd.isna(sigma):
            return None
        mu = excess.mean()
        sharpe = (mu / sigma) * (periods ** 0.5)
        return float(sharpe)

    def describe_cache(self, series: str | None = None) -> RiskFreeCacheInfo:
        """Return metadata about cached observations."""

        series_id = series or self.default_series
        with self._connect() as conn:
            self._ensure_tables(conn)
            return self._get_cache_info(conn, series_id)

    def fetch_recent(self, limit: int = 5, series: str | None = None) -> pd.DataFrame:
        """Return the most recent cached observations."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        series_id = series or self.default_series
        with self._connect() as conn:
            self._ensure_tables(conn)
            query = (
                "SELECT date, rate FROM risk_free_rates WHERE series=? "
                "ORDER BY date DESC LIMIT ?"
            )
            rows = conn.execute(query, (series_id, int(limit))).fetchall()
        df = pd.DataFrame(rows, columns=["date", "rate"])
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"], utc=False)
        return df.sort_values("date", ascending=False).reset_index(drop=True)

    def purge(self, series: str | None = None) -> None:
        """Remove cached data for the specified series."""

        series_id = series or self.default_series
        with self._connect() as conn:
            self._ensure_tables(conn)
            conn.execute("DELETE FROM risk_free_rates WHERE series=?", (series_id,))
            conn.execute("DELETE FROM risk_free_updates WHERE series=?", (series_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @contextmanager
    def _connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_free_rates (
                series TEXT NOT NULL,
                date   TEXT NOT NULL,
                rate   REAL NOT NULL,
                PRIMARY KEY (series, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_free_updates (
                series TEXT PRIMARY KEY,
                last_updated TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def _get_cache_info(
        self, conn: sqlite3.Connection, series: str
    ) -> RiskFreeCacheInfo:
        cur = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM risk_free_rates WHERE series=?",
            (series,),
        )
        row = cur.fetchone()
        start_date = dt.date.fromisoformat(row[0]) if row and row[0] else None
        end_date = dt.date.fromisoformat(row[1]) if row and row[1] else None
        rows = int(row[2]) if row and row[2] is not None else 0

        meta = conn.execute(
            "SELECT last_updated FROM risk_free_updates WHERE series=?",
            (series,),
        ).fetchone()
        last_updated = dt.datetime.fromisoformat(meta[0]) if meta and meta[0] else None
        if last_updated is not None and last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=dt.UTC)
        return RiskFreeCacheInfo(series, start_date, end_date, rows, last_updated)

    def _needs_refresh(
        self,
        info: RiskFreeCacheInfo,
        start: dt.date,
        end: dt.date,
    ) -> bool:
        if info.start_date is None or info.end_date is None:
            return True
        if start < info.start_date or end > info.end_date:
            return True
        if self.ttl_days is None:
            return False
        if info.last_updated is None:
            return True
        age = _utc_now() - info.last_updated
        return age > dt.timedelta(days=self.ttl_days)

    def _refresh_range(
        self,
        conn: sqlite3.Connection,
        series: str,
        start: dt.date,
        end: dt.date,
    ) -> None:
        padded_start = start - dt.timedelta(days=self.padding_days)
        padded_end = end + dt.timedelta(days=self.padding_days)
        df = self._download_range(series, padded_start, padded_end)
        if df.empty:
            raise RiskFreeRateFetchError(
                f"No observations returned from FRED for series {series}."
            )
        self._store_rates(conn, series, df)
        conn.execute(
            "INSERT INTO risk_free_updates(series, last_updated) VALUES(?, ?) "
            "ON CONFLICT(series) DO UPDATE SET last_updated=excluded.last_updated",
            (series, _utc_now().isoformat()),
        )
        conn.commit()

    def _store_rates(
        self, conn: sqlite3.Connection, series: str, df: pd.DataFrame
    ) -> None:
        payload = [
            (series, d.strftime("%Y-%m-%d"), float(r))
            for d, r in zip(df["date"], df["daily_rate"], strict=False)
            if pd.notna(r)
        ]
        if not payload:
            raise RiskFreeRateFetchError("Downloaded data contains no valid observations.")
        conn.executemany(
            "INSERT OR REPLACE INTO risk_free_rates(series, date, rate) VALUES(?, ?, ?)",
            payload,
        )

    def _download_range(
        self,
        series: str,
        start: dt.date,
        end: dt.date,
        *,
        retries: int = 5,
        backoff_seconds: float = 1.5,
    ) -> pd.DataFrame:
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise RiskFreeRateFetchError("FRED_API_KEY is not configured in the environment.")

        params = {
            "series_id": series,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.strftime("%Y-%m-%d"),
            "observation_end": end.strftime("%Y-%m-%d"),
            "frequency": "d",
            "aggregation_method": "avg",
        }

        for attempt in range(max(1, retries)):
            response = self.session.get(FRED_URL, params=params, timeout=30)
            if response.status_code == 429 and attempt + 1 < retries:
                sleep_for = backoff_seconds * (attempt + 1)
                time.sleep(sleep_for)
                continue
            try:
                response.raise_for_status()
            except requests.RequestException as exc:  # pragma: no cover - network guard
                raise RiskFreeRateFetchError(str(exc)) from exc
            data = response.json().get("observations", [])
            df = pd.DataFrame(data)
            if df.empty:
                return pd.DataFrame(columns=["date", "daily_rate"])
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            df["annual_rate"] = (
                pd.to_numeric(df["value"], errors="coerce") / 100.0
            )
            df = df.dropna(subset=["date", "annual_rate"])
            if df.empty:
                return pd.DataFrame(columns=["date", "daily_rate"])
            df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
            df["daily_rate"] = self._annual_to_daily(df["annual_rate"])
            return df[["date", "daily_rate"]]

        raise RiskFreeRateFetchError("Exceeded maximum retries when fetching from FRED.")

    @staticmethod
    def _annual_to_daily(annual_rate: pd.Series) -> pd.Series:
        return (1.0 + annual_rate).pow(1.0 / _TRADING_DAYS_PER_YEAR) - 1.0

    @staticmethod
    def _normalize_date(value: dt.date | dt.datetime | str) -> dt.date:
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        if isinstance(value, str):
            return dt.datetime.strptime(value, "%Y-%m-%d").date()
        raise TypeError("Date value must be date, datetime, or YYYY-MM-DD string")


__all__ = [
    "RiskFreeCacheInfo",
    "RiskFreeRateService",
    "RiskFreeRateServiceError",
]
