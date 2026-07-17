"""Atomic persistence for current and frozen legacy selection artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .contracts import (
    LEGACY_STABILITY_PROMPT_VERSION,
    PROMPT_VERSION,
    RANKING_ONLY_PROMPT_VERSION,
    SelectionArtifact,
)
from .ranking_policy_contract import (
    BOUNDED_RANKING_PROMPT_VERSION,
    BOUNDED_RANKING_V2_PROMPT_VERSION,
)


def write_selection(artifact: SelectionArtifact, output_path: str | Path) -> Path:
    """Publish a complete current artifact atomically, refusing every overwrite."""

    current_versions = {
        PROMPT_VERSION,
        RANKING_ONLY_PROMPT_VERSION,
        BOUNDED_RANKING_PROMPT_VERSION,
        BOUNDED_RANKING_V2_PROMPT_VERSION,
    }
    if artifact.prompt_version not in current_versions:
        raise ValueError(
            "only artifacts using the current prompt version may be published"
        )
    return _write_selection_payload(artifact, output_path)


def write_stability_selection(
    artifact: SelectionArtifact, output_path: str | Path
) -> Path:
    """Persist a legacy stability result on an isolated research-only path."""

    if artifact.prompt_version != LEGACY_STABILITY_PROMPT_VERSION:
        raise ValueError("stability output requires the frozen legacy prompt version")
    if artifact.eligible_as_oos_evidence:
        raise ValueError("stability output must remain ineligible as OOS evidence")
    return _write_selection_payload(artifact, output_path)


def _write_selection_payload(
    artifact: SelectionArtifact, output_path: str | Path
) -> Path:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = artifact.model_dump_json(indent=2)
    SelectionArtifact.model_validate_json(serialized, strict=True)
    payload = f"{serialized}\n".encode()
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise FileExistsError(
                "selection output already exists; reuse it or choose a new path: "
                f"{destination}"
            ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


__all__ = ["write_selection", "write_stability_selection"]
