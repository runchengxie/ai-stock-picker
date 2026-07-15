#!/usr/bin/env python3
"""Run the complete local quality gate from one command."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _commands() -> tuple[tuple[str, ...], ...]:
    return (
        ("uv", "lock", "--check"),
        ("ruff", "check", "."),
        ("ruff", "format", "--check", "."),
        ("ty", "check"),
        (sys.executable, "-m", "pytest"),
        (sys.executable, "scripts/dev/coverage_ratchet.py"),
        (
            sys.executable,
            "scripts/dev/maintainability_metrics.py",
            "--ratchet",
        ),
        (sys.executable, "-m", "build"),
    )


def _run(command: Sequence[str], *, cwd: Path) -> int:
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode


def main() -> int:
    root = _repo_root()
    commands = _commands()
    for index, command in enumerate(commands, 1):
        print(f"[{index}/{len(commands)}]", end=" ", flush=True)
        return_code = _run(command, cwd=root)
        if return_code != 0:
            return return_code
    print("\nAll local checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
