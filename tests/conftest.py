from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def generic_payload(market: str = "US") -> dict[str, Any]:
    rows = (
        [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "score": 9.0,
                "topic": "Technology",
                "features": {"quality": 0.9},
            },
            {
                "symbol": "BRK.B",
                "name": "Berkshire Hathaway",
                "score": 8.0,
                "topic": "Financials",
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft Corp.",
                "score": 7.0,
                "topic": "Software",
            },
        ]
        if market == "US"
        else [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "score": 9.0,
                "topic": "银行",
            },
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "score": 8.0,
                "topic": "金融科技",
            },
            {
                "symbol": "430047.BJ",
                "name": "诺思兰德",
                "score": 7.0,
                "topic": "医药",
            },
        ]
    )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "stock_candidate_universe",
        "market": market,
        "observation_date": "2026-07-14",
        "generated_at": (
            "2026-07-15T08:30:00-04:00"
            if market == "US"
            else "2026-07-15T06:00:00+08:00"
        ),
        "data_cutoff": "2026-07-14",
        "universe_size": len(rows),
        "candidates": rows,
    }


def hot_payload() -> dict[str, Any]:
    deferred = {
        "available": False,
        "reason": "future_data_excluded_from_generation",
        "horizons": {},
    }
    rows = [
        {
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "score": 9.0,
            "relevance": 0.9,
            "source_topics": ["银行"],
            "source_concepts": ["价值"],
            "trend_score": 0.8,
        },
        {
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "score": 8.0,
            "relevance": 0.8,
            "source_topics": ["金融科技"],
            "source_concepts": ["银行"],
            "trend_score": 0.7,
        },
    ]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "hot_sector_candidate_universe",
        "market": "CN",
        "date": "2026-07-14",
        "date_int": "20260714",
        "observation_date": "20260714",
        "data_cutoff": "20260714",
        "data_cutoff_semantics": "end_of_day",
        "execution_not_before": "next_trading_session",
        "future_data_included": False,
        "generated_at": "2026-07-15T06:00:00+08:00",
        "provenance": {
            "timezone": "Asia/Shanghai",
            "observation_date": "20260714",
            "data_cutoff": "20260714",
            "future_data_included": False,
            "artifact_role": "candidate_universe",
            "strict_point_in_time": False,
            "rotation": {
                "as_of_date": "20260714",
                "signal_date": "20260714",
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
        "topics": [
            {
                "topic": "银行",
                "weight": 0.8,
                "reasoning": "主题示例",
                "related_concepts": ["价值"],
                "source_signals": ["example"],
            }
        ],
        "candidate_universe": rows,
        "universe_size": len(rows),
        "config_snapshot": {},
        "data_sources": {},
        "quality_report": dict(deferred),
        "outcome_report": dict(deferred),
    }


def write_payload(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def us_manifest(tmp_path: Path) -> Path:
    return write_payload(tmp_path / "us.json", generic_payload("US"))


@pytest.fixture
def cn_manifest(tmp_path: Path) -> Path:
    return write_payload(tmp_path / "cn.json", generic_payload("CN"))


@pytest.fixture
def hot_manifest(tmp_path: Path) -> Path:
    return write_payload(tmp_path / "hot.json", hot_payload())
