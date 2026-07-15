from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_stock_picker.selection import build_selection_plan, create_selection
from ai_stock_picker.storage import write_selection


def response(symbol: str) -> str:
    return json.dumps(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "confidence_score": 8,
                    "reasoning": (
                        "The overall candidate score supports the relative ranking."
                    ),
                    "risk_note": (
                        "The overall candidate score is the only supplied basis for "
                        "this risk note."
                    ),
                }
            ]
        }
    )


def artifact_for(path: Path):
    plan = build_selection_plan(
        candidates_path=path,
        as_of=date(2026, 7, 15),
        top_n=1,
        style="quality",
        response_language="en",
        provider="deepseek",
    )
    return create_selection(
        plan,
        response("AAPL"),
        generated_at=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
    )


def test_write_selection_round_trip(us_manifest: Path, tmp_path: Path) -> None:
    artifact = artifact_for(us_manifest)
    output = write_selection(artifact, tmp_path / "nested" / "selection.json")
    trace = json.loads(output.read_text())["generation_trace"]
    assert trace["candidate_source"] == "us.json"


def test_write_selection_never_overwrites(us_manifest: Path, tmp_path: Path) -> None:
    artifact = artifact_for(us_manifest)
    output = tmp_path / "selection.json"
    output.write_text("existing\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        write_selection(artifact, output)
    assert output.read_text() == "existing\n"


def test_concurrent_writers_have_one_winner(us_manifest: Path, tmp_path: Path) -> None:
    artifact = artifact_for(us_manifest)
    output = tmp_path / "selection.json"

    def attempt(_: int) -> bool:
        try:
            write_selection(artifact, output)
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == [False, True]
    assert list(tmp_path.glob(".selection.json.*.tmp")) == []
