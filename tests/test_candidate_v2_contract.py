from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import write_manifest

from stock_analysis.ai_lab.candidates import (
    SOURCE_CONCEPTS_POLICY_SHA256,
    load_candidate_universe,
)
from stock_analysis.ai_lab.ranking_policy import numeric_ranking_method
from stock_analysis.ai_lab.selection import build_selection_plan, create_selection

_POLICY = {
    "policy_id": "hotsector.source_concepts.theme_only",
    "version": "1.0.0",
    "allowed": ["theme", "concept", "related_concepts"],
    "excluded": ["tag", "lu_desc", "status", "rank_reason", "limit_type"],
    "normalizer_id": "hotsector.concept_token.v1",
    "canonical_sha256": SOURCE_CONCEPTS_POLICY_SHA256,
}
_MODEL_IDENTITY = {
    "model_id": "hotsector-theme-v3",
    "model_version": "3.0.0",
    "feature_set_id": "topic-concept-hotspot-overlay-theme-only-v1",
}


def _v2_manifest(tmp_path: Path, **overrides: Any) -> Path:
    rows = [
        {
            "ts_code": "600000.SH",
            "name": "候选甲",
            "score": 9.0,
            "relevance": 0.9,
            "source_topics": ["银行"],
            "source_concepts": ["金融科技"],
            "source_event_tags": ["事件标签秘密"],
            "source_event_statuses": ["事件状态秘密"],
            "source_event_reasons": ["事件原因秘密"],
            "trend_score": 0.8,
            "risk_score": 0.7,
        }
    ]
    metadata: dict[str, Any] = {
        "schema_version": "2.0.0",
        "source_concepts_policy": _POLICY,
        "model_identity": _MODEL_IDENTITY,
    }
    metadata.update(overrides)
    return write_manifest(tmp_path / "candidate-v2.json", rows=rows, **metadata)


def test_candidate_v2_is_dual_read_and_event_fields_never_enter_prompt(
    tmp_path: Path,
) -> None:
    path = _v2_manifest(tmp_path)
    universe = load_candidate_universe(path, market="CN", as_of=date(2026, 7, 15))
    plan = build_selection_plan(
        market="CN",
        candidates_path=path,
        as_of=date(2026, 7, 15),
        top_n=1,
    )

    assert universe.input_contract == "hot_sector_candidate_universe_v2"
    assert numeric_ranking_method(universe) == "relevance_desc_score_desc_symbol_asc"
    assert plan.universe.candidates[0].features["source_concepts"] == ["金融科技"]
    assert "事件标签秘密" not in plan.prompt
    assert "事件状态秘密" not in plan.prompt
    assert "事件原因秘密" not in plan.prompt

    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                }
            ]
        },
        ensure_ascii=False,
    )
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 8, tzinfo=timezone.utc),
    )
    assert artifact.input_contract == "hot_sector_candidate_universe_v2"


def test_candidate_v2_rejects_noncanonical_policy_and_missing_event_arrays(
    tmp_path: Path,
) -> None:
    bad_policy = {**_POLICY, "canonical_sha256": "0" * 64}
    with pytest.raises(ValueError, match="source_concepts_policy"):
        load_candidate_universe(
            _v2_manifest(tmp_path, source_concepts_policy=bad_policy),
            market="CN",
            as_of=date(2026, 7, 15),
        )

    payload = json.loads(_v2_manifest(tmp_path).read_bytes())
    payload["candidate_universe"][0].pop("source_event_reasons")
    missing = tmp_path / "missing-events.json"
    missing.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="source_event_reasons"):
        load_candidate_universe(missing, market="CN", as_of=date(2026, 7, 15))


def test_v1_candidate_contract_remains_unchanged(cn_manifest: Path) -> None:
    universe = load_candidate_universe(
        cn_manifest, market="CN", as_of=date(2026, 7, 15)
    )
    assert universe.input_contract == "hot_sector_candidate_universe_v1"
