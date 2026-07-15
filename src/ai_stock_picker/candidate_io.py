"""Safe candidate-manifest file input."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import cast

from .candidate_models import RawManifest

_MAX_INPUT_BYTES = 10_000_000


def read_candidate_manifest(path: str | Path) -> RawManifest:
    """Read a bounded JSON manifest and calculate its content fingerprint."""

    candidate_path = Path(path).expanduser().resolve()
    if not candidate_path.is_file():
        raise ValueError(f"candidate input does not exist: {candidate_path}")
    if candidate_path.suffix.lower() != ".json":
        raise ValueError(
            "candidate input must be a versioned .json manifest; "
            "use `aipick migrate-csv` for legacy CSV"
        )
    raw = candidate_path.read_bytes()
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError("candidate input exceeds the 10 MB safety limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid candidate JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be a versioned candidate manifest object")
    return RawManifest(
        path=candidate_path,
        source_name=candidate_path.name,
        payload=cast(dict[str, object], payload),
        input_sha256=sha256(raw).hexdigest(),
    )


__all__ = ["read_candidate_manifest"]
