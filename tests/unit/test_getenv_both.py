import pytest
from stock_analysis.execution.broker.longport_client import getenv_both

pytestmark = pytest.mark.unit


def test_prefers_new_env_var(monkeypatch):
    monkeypatch.setenv("LONGPORT_APP_KEY", "new")
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "old")
    assert getenv_both("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY") == "new"


def test_returns_new_when_only_new(monkeypatch):
    monkeypatch.setenv("LONGPORT_APP_KEY", "new")
    monkeypatch.delenv("LONGBRIDGE_APP_KEY", raising=False)
    assert getenv_both("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY") == "new"


def test_falls_back_to_old(monkeypatch):
    monkeypatch.delenv("LONGPORT_APP_KEY", raising=False)
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "old")
    assert getenv_both("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY") == "old"


def test_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("LONGPORT_APP_KEY", raising=False)
    monkeypatch.delenv("LONGBRIDGE_APP_KEY", raising=False)
    assert getenv_both("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY", "default") == "default"
