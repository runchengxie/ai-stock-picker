from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _default_rows(market: str) -> list[dict[str, Any]]:
    if market == "CN":
        return [
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "score": 9.0,
                "relevance": 0.9,
                "source_topics": ["银行"],
                "source_concepts": [],
                "trend_score": 0.8,
            },
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "score": 8.0,
                "relevance": 0.8,
                "source_topics": ["金融科技"],
                "source_concepts": [],
                "trend_score": 0.7,
            },
            {
                "ts_code": "430047.BJ",
                "name": "诺思兰德",
                "score": 7.0,
                "relevance": 0.7,
                "source_topics": ["医药"],
                "source_concepts": [],
                "trend_score": 0.6,
            },
        ]
    return [
        {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "score": 9.0,
            "sector": "Technology",
        },
        {
            "ticker": "BRK.B",
            "company_name": "Berkshire Hathaway",
            "score": 8.0,
            "sector": "Financials",
        },
        {
            "ticker": "MSFT",
            "company_name": "Microsoft Corp.",
            "score": 7.0,
            "industry": "Software",
        },
    ]


def _hot_contract_metadata() -> dict[str, object]:
    deferred = {
        "available": False,
        "reason": "future_data_excluded_from_generation",
        "horizons": {},
    }
    return {
        "schema_version": "1.0.0",
        "artifact_type": "hot_sector_candidate_universe",
        "market": "CN",
        "observation_date": "20260714",
        "data_cutoff_semantics": "end_of_day",
        "execution_not_before": "next_trading_session",
        "future_data_included": False,
        "topics": [],
        "data_sources": {},
        "config_snapshot": {},
        "provenance": {
            "timezone": "Asia/Shanghai",
            "observation_date": "20260714",
            "data_cutoff": "20260714",
            "future_data_included": False,
            "artifact_role": "candidate_universe",
            "strict_point_in_time": False,
            "rotation": {
                "provenance_level": "signal_date_only",
                "strict_point_in_time": False,
                "publisher_receipt_verified": False,
            },
        },
        "evidence": {
            "strict_point_in_time": False,
            "out_of_sample_claim": False,
            "temporal_context": "post_observation_generation",
            "limitations": [
                "rotation_publisher_receipt_unavailable",
                "candidate_artifact_does_not_establish_out_of_sample_validity",
                "post_observation_reconstruction_not_oos",
            ],
        },
        "quality_report": dict(deferred),
        "outcome_report": dict(deferred),
    }


def write_manifest(
    path: Path,
    *,
    market: str = "CN",
    rows: list[dict[str, Any]] | None = None,
    **overrides: object,
) -> Path:
    if rows is None:
        rows = _default_rows(market)
    elif market == "CN":
        rows = [
            {
                "relevance": 0.5,
                "source_topics": [],
                "source_concepts": [],
                **row,
            }
            for row in rows
        ]
    payload: dict[str, object] = {
        "date": "2026-07-14",
        "date_int": "20260714",
        "generated_at": (
            "2026-07-15T06:00:00+08:00"
            if market == "CN"
            else "2026-07-15T08:30:00-04:00"
        ),
        "data_cutoff": "2026-07-14",
        "universe_size": len(rows),
        "candidate_universe" if market == "CN" else "candidates": rows,
    }
    if market == "CN":
        payload.update(_hot_contract_metadata())
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def cn_manifest(tmp_path: Path) -> Path:
    return write_manifest(tmp_path / "cn.json")


@pytest.fixture
def us_manifest(tmp_path: Path) -> Path:
    return write_manifest(tmp_path / "us.json", market="US")
