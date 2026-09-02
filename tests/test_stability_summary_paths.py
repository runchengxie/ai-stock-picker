from __future__ import annotations

import json
from pathlib import Path

from stock_analysis.ai_lab.stability_analysis import summarize_stability_results


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_summary_uses_result_relative_ranking_sources(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    _write_json(
        campaign / "manifest.json",
        {
            "artifact_type": "ai_stability_campaign",
            "status": "planned",
            "campaign_id": "portable-demo",
            "top_n": 3,
            "variants": [
                {"trial_id": "canonical"},
                {"trial_id": "shuffle_101"},
            ],
        },
    )
    results = tmp_path / "results"
    canonical_payload = {
        "artifact_type": "ai_stock_selection",
        "picks": [
            {"rank": 1, "symbol": "999001.SZ"},
            {"rank": 2, "symbol": "999002.SZ"},
            {"rank": 3, "symbol": "999003.SZ"},
        ],
    }
    _write_json(results / "canonical.json", canonical_payload)
    _write_json(
        results / "canonical.evidence" / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "complete",
            "campaign_id": "portable-demo",
            "trial_id": "canonical",
            "top_n": 3,
            "selection_path": "selection.json",
        },
    )
    _write_json(results / "canonical.evidence" / "selection.json", canonical_payload)
    _write_json(
        results / "shuffle_101.evidence" / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "rejected",
            "campaign_id": "portable-demo",
            "trial_id": "shuffle_101",
            "top_n": 3,
            "ranking_contract": "passed",
            "publication_contract": "failed",
            "ranking_diagnostic_path": "ranking_diagnostic.json",
        },
    )
    _write_json(
        results / "shuffle_101.evidence" / "ranking_diagnostic.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "ai_ranking_diagnostic",
            "symbols": ["999001.SZ", "999003.SZ", "999002.SZ"],
        },
    )

    summary = summarize_stability_results(campaign, results)
    by_trial = {arm["trial_id"]: arm for arm in summary["arms"]}

    assert by_trial["canonical"]["ranking_source"] == "canonical.json"
    assert (
        by_trial["shuffle_101"]["ranking_source"]
        == "shuffle_101.evidence/ranking_diagnostic.json"
    )
