from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_analysis.ai_lab.stability_analysis import summarize_stability_results


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    variants = [
        {"trial_id": "canonical", "trial_path": "trials/canonical/trial.json"},
        {"trial_id": "shuffle_101", "trial_path": "trials/shuffle_101/trial.json"},
        {"trial_id": "shuffle_202", "trial_path": "trials/shuffle_202/trial.json"},
        {"trial_id": "shuffle_303", "trial_path": "trials/shuffle_303/trial.json"},
        {"trial_id": "opaque_404", "trial_path": "trials/opaque_404/trial.json"},
    ]
    _write_json(
        root / "manifest.json",
        {
            "schema_version": "2.0.0",
            "artifact_type": "ai_stability_campaign",
            "status": "planned",
            "campaign_id": "demo-order-sensitivity",
            "top_n": 3,
            "variants": variants,
        },
    )
    for variant in variants:
        _write_json(
            root / str(variant["trial_path"]),
            {
                "artifact_type": "ai_stability_trial",
                "trial_id": variant["trial_id"],
            },
        )
    return root


def _selection(path: Path, *symbols: str) -> None:
    payload = {
        "artifact_type": "ai_stock_selection",
        "picks": [
            {"rank": rank, "symbol": symbol}
            for rank, symbol in enumerate(symbols, 1)
        ],
    }
    _write_json(path, payload)
    evidence = path.with_suffix(".evidence")
    _write_json(
        evidence / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "complete",
            "campaign_id": "demo-order-sensitivity",
            "trial_id": path.stem,
            "top_n": 3,
            "selection_path": "selection.json",
        },
    )
    _write_json(evidence / "selection.json", payload)


def test_summarizes_complete_campaign_against_canonical(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "shuffle_101.json", "999001.SZ", "999003.SZ", "999002.SZ")
    _selection(results / "shuffle_202.json", "999004.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "shuffle_303.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "opaque_404.json", "999001.SZ", "999002.SZ", "999003.SZ")

    summary = summarize_stability_results(campaign, results)

    assert summary["status"] == "complete"
    assert summary["campaign_id"] == "demo-order-sensitivity"
    assert summary["completed_trials"] == [
        "canonical",
        "shuffle_101",
        "shuffle_202",
        "shuffle_303",
        "opaque_404",
    ]
    assert summary["missing_trials"] == []
    assert summary["canonical_ranking"] == [
        "999001.SZ",
        "999002.SZ",
        "999003.SZ",
    ]

    by_trial = {arm["trial_id"]: arm for arm in summary["arms"]}
    assert by_trial["shuffle_101"]["top1_matches_canonical"] is True
    assert by_trial["shuffle_101"]["exact_ranking_matches_canonical"] is False
    assert by_trial["shuffle_101"]["top_n_jaccard_vs_canonical"] == pytest.approx(1.0)
    assert by_trial["shuffle_101"][
        "mean_absolute_rank_shift_vs_canonical"
    ] == pytest.approx(2 / 3)
    assert by_trial["shuffle_202"]["top1_matches_canonical"] is False
    assert by_trial["shuffle_202"]["top_n_jaccard_vs_canonical"] == pytest.approx(0.5)

    aggregate = summary["aggregate"]
    assert aggregate["completed_noncanonical_arms"] == 4
    assert aggregate["top1_agreement_rate_vs_canonical"] == pytest.approx(0.75)
    assert aggregate["exact_ranking_agreement_rate_vs_canonical"] == pytest.approx(0.5)
    assert aggregate["shuffle"]["completed_arms"] == 3
    assert aggregate["opaque"]["completed_arms"] == 1


def test_uses_ranking_diagnostic_when_publication_was_rejected(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _write_json(
        results / "shuffle_101.evidence" / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "rejected",
            "campaign_id": "demo-order-sensitivity",
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

    arm = next(arm for arm in summary["arms"] if arm["trial_id"] == "shuffle_101")
    assert arm["status"] == "ranking_only"
    assert arm["ranking"] == ["999001.SZ", "999003.SZ", "999002.SZ"]
    assert "shuffle_101" in summary["completed_trials"]
    assert summary["status"] == "partial"


def test_marks_rejected_and_missing_trials_without_silently_dropping_them(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _write_json(
        results / "shuffle_101.evidence" / "manifest.json",
        {
            "artifact_type": "ai_selection_evidence",
            "status": "rejected",
            "campaign_id": "demo-order-sensitivity",
            "trial_id": "shuffle_101",
            "top_n": 3,
            "ranking_contract": "failed",
            "publication_contract": "not_evaluated",
            "ranking_diagnostic_path": None,
        },
    )

    summary = summarize_stability_results(campaign, results)

    by_trial = {arm["trial_id"]: arm for arm in summary["arms"]}
    assert by_trial["shuffle_101"]["status"] == "rejected"
    assert by_trial["shuffle_202"]["status"] == "missing"
    assert summary["rejected_trials"] == ["shuffle_101"]
    assert summary["missing_trials"] == [
        "shuffle_202",
        "shuffle_303",
        "opaque_404",
    ]
    assert summary["aggregate"]["completed_noncanonical_arms"] == 0
    assert summary["aggregate"]["top1_agreement_rate_vs_canonical"] is None


def test_requires_a_completed_canonical_ranking(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"

    with pytest.raises(ValueError, match="canonical trial must have a usable ranking"):
        summarize_stability_results(campaign, results)


def test_rejects_rankings_that_do_not_match_campaign_top_n(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _selection(results / "shuffle_101.json", "999001.SZ", "999002.SZ")

    with pytest.raises(ValueError, match="ranking length must equal campaign top_n=3"):
        summarize_stability_results(campaign, results)


def test_rejects_orphan_ranking_diagnostic_without_rejected_evidence_manifest(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _selection(results / "canonical.json", "999001.SZ", "999002.SZ", "999003.SZ")
    _write_json(
        results / "shuffle_101.evidence" / "ranking_diagnostic.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "ai_ranking_diagnostic",
            "symbols": ["999001.SZ", "999003.SZ", "999002.SZ"],
        },
    )

    with pytest.raises(
        ValueError, match="ranking diagnostic requires rejected evidence manifest"
    ):
        summarize_stability_results(campaign, results)


def test_rejects_non_selection_artifact(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _write_json(
        results / "canonical.json",
        {
            "artifact_type": "some_other_artifact",
            "picks": [
                {"rank": 1, "symbol": "999001.SZ"},
                {"rank": 2, "symbol": "999002.SZ"},
                {"rank": 3, "symbol": "999003.SZ"},
            ],
        },
    )

    with pytest.raises(ValueError, match="selection artifact_type is invalid"):
        summarize_stability_results(campaign, results)


def test_rejects_complete_selection_without_matching_evidence_bundle(
    tmp_path: Path,
) -> None:
    campaign = _campaign(tmp_path)
    results = tmp_path / "results"
    _write_json(
        results / "canonical.json",
        {
            "artifact_type": "ai_stock_selection",
            "picks": [
                {"rank": 1, "symbol": "999001.SZ"},
                {"rank": 2, "symbol": "999002.SZ"},
                {"rank": 3, "symbol": "999003.SZ"},
            ],
        },
    )

    with pytest.raises(
        ValueError, match="complete selection requires matching evidence bundle"
    ):
        summarize_stability_results(campaign, results)
