#!/usr/bin/env python3
"""Add only owner-validated prospective day summaries to a reviewed snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_analysis.ai_lab.shadow_validation import validate_shadow_day


def public_day(path: Path) -> dict[str, object]:
    verified = validate_shadow_day(path)
    if verified["evidence_status"] != "prospective_bound":
        raise ValueError("offline or unbound rehearsals are not daily observations")
    return {
        "date": verified["signal_date"],
        "arm": verified["arm"],
        "model": verified["model_partition"],
        "status": verified["consensus_status"],
        "valid_repetitions": verified["valid_repetitions"],
        "evidence_status": verified["evidence_status"],
        "consensus_sha256": verified["consensus_manifest_sha256"],
        "input_sha256": verified["input_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--day-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.expanduser().resolve()
    if root == output or root in output.parents:
        raise ValueError("snapshot output must stay outside the checkout")
    data = json.loads(args.snapshot.read_text())
    days = [public_day(path) for path in args.day_dir]
    data["daily"]["rows"].extend(days)
    with output.open("x") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
