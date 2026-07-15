from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_stock_picker.csv_migration import migrate_csv


def test_migrate_us_csv_to_common_manifest(tmp_path: Path) -> None:
    source = tmp_path / "us.csv"
    source.write_text(
        "ticker,company_name,score,sector\nAAPL,Apple Inc.,9,Technology\n",
        encoding="utf-8",
    )
    output = migrate_csv(
        source,
        tmp_path / "manifest.json",
        market="US",
        observation_date=date(2026, 7, 14),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        data_cutoff=date(2026, 7, 14),
    )
    payload = json.loads(output.read_text())
    assert payload["artifact_type"] == "stock_candidate_universe"
    assert payload["market"] == "US"
    assert payload["candidates"][0]["symbol"] == "AAPL"


def test_migrate_cn_csv_parses_list_topics(tmp_path: Path) -> None:
    source = tmp_path / "cn.csv"
    source.write_text(
        "ts_code,name,score,source_topics\n600000.SH,浦发银行,8,\"['银行', '价值']\"\n",
        encoding="utf-8",
    )
    output = migrate_csv(
        source,
        tmp_path / "manifest.json",
        market="CN",
        observation_date=date(2026, 7, 14),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        data_cutoff=date(2026, 7, 14),
    )
    payload = json.loads(output.read_text())
    assert payload["candidates"][0]["topic"] == "银行 / 价值"


def test_migration_rejects_bad_dates_and_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "us.csv"
    source.write_text(
        "ticker,company_name,score\nAAPL,Apple,9\nAAPL,Apple,8\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="data_cutoff"):
        migrate_csv(
            source,
            tmp_path / "manifest.json",
            market="US",
            observation_date=date(2026, 7, 14),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            data_cutoff=date(2026, 7, 15),
        )
    with pytest.raises(ValueError, match="unique"):
        migrate_csv(
            source,
            tmp_path / "manifest.json",
            market="US",
            observation_date=date(2026, 7, 14),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            data_cutoff=date(2026, 7, 14),
        )
