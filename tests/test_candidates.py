from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import generic_payload, hot_payload, write_payload

from ai_stock_picker.candidates import load_candidate_universe
from ai_stock_picker.time_utils import parse_date


def test_parse_date_accepts_supported_formats() -> None:
    assert parse_date("2026-07-15") == date(2026, 7, 15)
    assert parse_date("20260715") == date(2026, 7, 15)


def test_parse_date_rejects_ambiguous_format() -> None:
    with pytest.raises(ValueError, match="invalid date"):
        parse_date("07/15/2026")


def test_generic_manifest_declares_market(us_manifest: Path) -> None:
    universe = load_candidate_universe(us_manifest, as_of=date(2026, 7, 15))
    assert universe.market == "US"
    assert universe.input_contract == "stock_candidate_universe_v1"
    assert universe.point_in_time_assurance == "unverified"
    assert universe.source_name == "us.json"
    assert universe.source_generated_at.utcoffset() == timedelta(hours=-4)
    assert [item.symbol for item in universe.candidates] == ["AAPL", "BRK.B", "MSFT"]
    assert universe.candidates[0].features == {"quality": 0.9}
    assert len(universe.input_sha256) == 64
    assert len(universe.candidate_symbols_sha256) == 64


def test_same_market_manifest_can_use_cn_symbols(cn_manifest: Path) -> None:
    universe = load_candidate_universe(cn_manifest, as_of=date(2026, 7, 15))
    assert universe.market == "CN"
    assert universe.candidates[0].symbol == "600000.SH"


def test_hot_sector_contract_preserves_assurance(hot_manifest: Path) -> None:
    universe = load_candidate_universe(hot_manifest, as_of=date(2026, 7, 15))
    assert universe.input_contract == "hot_sector_candidate_universe_v1"
    assert universe.point_in_time_assurance == "signal_date_only"
    assert universe.upstream_execution_not_before == "next_trading_session"
    assert universe.candidates[0].topic == "银行 / 价值"
    assert "rotation_publisher_receipt_unavailable" in universe.evidence_limitations


def test_csv_is_rejected_from_core_path(tmp_path: Path) -> None:
    path = tmp_path / "candidates.csv"
    path.write_text("symbol,name,score\nAAPL,Apple,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="migrate-csv"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))


def test_manifest_identity_and_market_are_strict(tmp_path: Path) -> None:
    payload = generic_payload("US")
    payload["schema_version"] = "9.9.9"
    path = write_payload(tmp_path / "bad.json", payload)
    with pytest.raises(ValueError, match="unsupported candidate contract"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))

    payload = generic_payload("US")
    payload["market"] = "HK"
    path = write_payload(tmp_path / "market.json", payload)
    with pytest.raises(ValueError, match="market must be"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))


def test_manifest_dates_and_size_are_validated(tmp_path: Path) -> None:
    payload = generic_payload("US")
    payload["observation_date"] = "2026-07-16"
    path = write_payload(tmp_path / "future.json", payload)
    with pytest.raises(ValueError, match="after selection"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))

    payload = generic_payload("US")
    payload["universe_size"] = 99
    path = write_payload(tmp_path / "size.json", payload)
    with pytest.raises(ValueError, match="row count"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))

    payload = generic_payload("US")
    payload["generated_at"] = "2026-07-15T08:30:00"
    path = write_payload(tmp_path / "time.json", payload)
    with pytest.raises(ValueError, match="explicit UTC offset"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))


def test_generic_rows_are_strict_and_bounded(tmp_path: Path) -> None:
    payload = generic_payload("US")
    rows = cast(list[dict[str, Any]], payload["candidates"])
    rows[0]["symbol"] = "600000.SH"
    path = write_payload(tmp_path / "wrong-symbol.json", payload)
    with pytest.raises(ValueError, match="invalid US symbol"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))

    payload = generic_payload("US")
    rows = cast(list[dict[str, Any]], payload["candidates"])
    rows[1]["symbol"] = "AAPL"
    path = write_payload(tmp_path / "duplicate.json", payload)
    with pytest.raises(ValueError, match="unique"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))

    payload = generic_payload("US")
    rows = cast(list[dict[str, Any]], payload["candidates"])
    rows[0]["score"] = "nan"
    path = write_payload(tmp_path / "score.json", payload)
    with pytest.raises(ValueError, match="finite"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))


def test_hot_sector_contract_rejects_incomplete_evidence(tmp_path: Path) -> None:
    payload = hot_payload()
    evidence = cast(dict[str, Any], payload["evidence"])
    evidence["limitations"] = []
    path = write_payload(tmp_path / "hot.json", payload)
    with pytest.raises(ValueError, match="limitations"):
        load_candidate_universe(path, as_of=date(2026, 7, 15))


def test_input_size_and_json_shape_are_bounded(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_bytes(b" " * 10_000_001)
    with pytest.raises(ValueError, match="10 MB"):
        load_candidate_universe(huge, as_of=date(2026, 7, 15))

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest object"):
        load_candidate_universe(array, as_of=date(2026, 7, 15))
