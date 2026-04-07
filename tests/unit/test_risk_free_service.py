"""Unit tests for the risk-free rate service."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from stock_analysis.shared.services.marketdata.risk_free import (
    RiskFreeCacheInfo,
    RiskFreeRateFetchError,
    RiskFreeRateService,
    RiskFreeRateServiceError,
)


def _build_service(tmp_path: Path, **kwargs: Any) -> RiskFreeRateService:
    """Create a service instance backed by a temporary SQLite database."""

    defaults = {
        "db_path": tmp_path / "risk_free.db",
        "default_series": "TEST",
        "padding_days": 0,
        "ttl_days": 5,
    }
    defaults.update(kwargs)
    return RiskFreeRateService(**defaults)


@pytest.mark.unit
def test_ensure_range_populates_cache(tmp_path, monkeypatch):
    """The service stores downloaded observations and returns cache metadata."""

    service = _build_service(tmp_path)

    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]).date,
            "daily_rate": [0.001, 0.002],
        }
    )
    calls = []

    def fake_download(
        series: str, start: dt.date, end: dt.date, **_: Any
    ) -> pd.DataFrame:
        calls.append((series, start, end))
        return data

    monkeypatch.setattr(service, "_download_range", fake_download)

    info = service.ensure_range(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    assert calls == [("TEST", dt.date(2024, 1, 1), dt.date(2024, 1, 2))]
    assert info.series == "TEST"
    assert info.rows == 2
    assert info.start_date == dt.date(2024, 1, 1)
    assert info.end_date == dt.date(2024, 1, 2)

    cached = service.describe_cache("TEST")
    assert cached.rows == 2
    assert cached.start_date == dt.date(2024, 1, 1)
    assert cached.end_date == dt.date(2024, 1, 2)


@pytest.mark.unit
def test_ensure_range_respects_ttl(tmp_path, monkeypatch):
    """A stale cache triggers a new download when TTL has expired."""

    service = _build_service(tmp_path, ttl_days=1)

    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-02-01", "2024-02-02"]).date,
            "daily_rate": [0.0005, 0.0006],
        }
    )

    calls = SimpleNamespace(count=0)

    def fake_download(series: str, start: dt.date, end: dt.date, **_: Any) -> pd.DataFrame:
        calls.count += 1
        return data

    monkeypatch.setattr(service, "_download_range", fake_download)

    # First population
    service.ensure_range(dt.date(2024, 2, 1), dt.date(2024, 2, 2))
    assert calls.count == 1

    # Age the cache manually beyond TTL
    with service._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE risk_free_updates SET last_updated=? WHERE series=?",
            ((dt.datetime.now(dt.UTC) - dt.timedelta(days=5)).isoformat(), "TEST"),
        )
        conn.commit()

    service.ensure_range(dt.date(2024, 2, 1), dt.date(2024, 2, 2))
    assert calls.count == 2


@pytest.mark.unit
def test_get_series_for_index_aligns_with_cache(tmp_path, monkeypatch):
    """Returned series is aligned to the requested index with forward fill."""

    service = _build_service(tmp_path)

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-03-01", "2024-03-04"]).date,
            "daily_rate": [0.001, 0.002],
        }
    )

    monkeypatch.setattr(service, "_download_range", lambda *_, **__: frame)
    service.ensure_range(dt.date(2024, 3, 1), dt.date(2024, 3, 4))

    index = pd.date_range("2024-03-01", periods=4, freq="D")
    series = service.get_series_for_index(index)

    assert list(series.index) == list(index)
    # First value is explicit, middle gaps are forward-filled, final value is explicit.
    assert series.iloc[0] == pytest.approx(0.001)
    assert series.iloc[1] == pytest.approx(0.001)
    assert series.iloc[2] == pytest.approx(0.001)
    assert series.iloc[3] == pytest.approx(0.002)


@pytest.mark.unit
def test_get_series_for_index_uses_fallback(tmp_path, monkeypatch, caplog):
    """When ensuring cache fails, the configured fallback rate is used."""

    service = _build_service(tmp_path, fallback_rate=0.0007)

    def boom(*_: Any, **__: Any) -> RiskFreeCacheInfo:
        raise RiskFreeRateServiceError("boom")

    monkeypatch.setattr(service, "ensure_range", boom)

    index = pd.date_range("2024-04-01", periods=3, freq="D")
    with caplog.at_level("WARNING"):
        series = service.get_series_for_index(index)

    assert all(value == pytest.approx(0.0007) for value in series)
    assert "Falling back to constant risk-free rate" in caplog.text


@pytest.mark.unit
def test_get_series_for_index_without_fallback_prompts_update(tmp_path, monkeypatch):
    """If fetching fails and no fallback is configured, an actionable error is raised."""

    service = _build_service(tmp_path, fallback_rate=None)

    def boom(*_: Any, **__: Any) -> RiskFreeCacheInfo:
        raise RiskFreeRateServiceError("no data")

    monkeypatch.setattr(service, "ensure_range", boom)

    index = pd.date_range("2024-04-01", periods=2, freq="D")

    with pytest.raises(RiskFreeRateServiceError) as excinfo:
        service.get_series_for_index(index)

    message = str(excinfo.value)
    assert "stockq rf update" in message
    assert "no data" in message


@pytest.mark.unit
def test_compute_sharpe_uses_cached_series(tmp_path):
    """Sharpe ratio is computed using cached daily risk-free observations."""

    service = _build_service(tmp_path)

    with service._connect() as conn:  # type: ignore[attr-defined]
        service._ensure_tables(conn)  # type: ignore[attr-defined]
        rows = [
            ("TEST", "2024-05-01", 0.0005),
            ("TEST", "2024-05-02", 0.0005),
            ("TEST", "2024-05-03", 0.0005),
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO risk_free_rates(series, date, rate) VALUES(?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO risk_free_updates(series, last_updated) VALUES(?, ?)",
            ("TEST", dt.datetime.now(dt.UTC).isoformat()),
        )
        conn.commit()

    returns = pd.Series(
        [0.003, 0.001, -0.002], index=pd.date_range("2024-05-01", periods=3, freq="D")
    )

    sharpe = service.compute_sharpe(returns)

    assert sharpe == pytest.approx(1.051314966, rel=1e-6)


@pytest.mark.unit
def test_download_range_parses_response(tmp_path, monkeypatch):
    """Raw FRED responses are converted to a clean daily-rate DataFrame."""

    service = _build_service(tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "dummy")

    payload = {
        "observations": [
            {"date": "2024-06-01", "value": "5.0"},
            {"date": "2024-06-02", "value": "5.5"},
        ]
    }

    class DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return payload

    class DummySession:
        def get(self, *_: Any, **__: Any) -> DummyResponse:
            return DummyResponse()

    service.session = DummySession()

    df = service._download_range(  # type: ignore[attr-defined]
        "TEST", dt.date(2024, 6, 1), dt.date(2024, 6, 2)
    )

    assert list(df.columns) == ["date", "daily_rate"]
    assert df.shape == (2, 2)
    assert df["date"].iloc[0] == dt.date(2024, 6, 1)
    assert df["daily_rate"].iloc[0] == pytest.approx(
        (1 + 0.05) ** (1 / 252) - 1
    )


@pytest.mark.unit
def test_download_range_missing_key_raises(tmp_path, monkeypatch):
    """Missing API keys surface a descriptive fetch error."""

    service = _build_service(tmp_path)
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(RiskFreeRateFetchError):
        service._download_range("TEST", dt.date(2024, 1, 1), dt.date(2024, 1, 2))
