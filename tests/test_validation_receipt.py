from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from stock_analysis.ai_lab.selection import build_selection_plan, create_selection
from stock_analysis.app.cli import main


def test_validate_can_emit_content_bound_receipt(
    cn_manifest: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = build_selection_plan(
        market="CN",
        candidates_path=cn_manifest,
        as_of=date(2026, 7, 15),
        top_n=1,
    )
    response = json.dumps(
        {
            "picks": [
                {
                    "symbol": "600000.SH",
                    "confidence_score": 8,
                    "reasoning": "依据 score 候选字段进行相对排序",
                    "risk_note": "仅依据 score，风险解读仍有信息边界",
                }
            ]
        },
        ensure_ascii=False,
    )
    artifact = create_selection(
        plan,
        response,
        generated_at=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "cn",
                "validate",
                "--selection",
                str(selection),
                "--candidates",
                str(cn_manifest),
                "--validation-receipt",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["schema_version"] == "1.0.0"
    assert receipt["artifact_type"] == "ai_stock_selection_validation_receipt"
    assert receipt["valid"] is True
    assert receipt["market"] == "CN"
    assert receipt["selection_sha256"] == sha256(selection.read_bytes()).hexdigest()
    assert receipt["selection_as_of"] == "2026-07-15"
    assert receipt["prompt_version"] == artifact.prompt_version
    assert receipt["picks"] == 1
    assert receipt["validation_profile"] == "current_full"
    assert receipt["prompt_hash_revalidated"] is True
    assert receipt["commentary_policy_revalidated"] is True
    assert receipt["response_sha256_verification"] == (
        "format_only_raw_response_unavailable"
    )
    assert receipt["evidence_manifest_sha256"] is None
