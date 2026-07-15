"""Atomic, no-overwrite JSON publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .contracts import SelectionArtifact


def write_selection(artifact: SelectionArtifact, output_path: str | Path) -> Path:
    """Publish a validated artifact atomically without overwriting."""

    serialized = artifact.model_dump_json(indent=2)
    SelectionArtifact.model_validate_json(serialized, strict=True)
    return write_new_bytes(output_path, f"{serialized}\n".encode())


def write_json_document(payload: dict[str, object], output_path: str | Path) -> Path:
    """Publish a JSON document atomically without overwriting."""

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return write_new_bytes(output_path, f"{serialized}\n".encode())


def write_new_bytes(output_path: str | Path, payload: bytes) -> Path:
    """Write bytes with exactly one winner for a destination path."""

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
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
                f"output already exists; reuse it or choose a new path: {destination}"
            ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


__all__ = ["write_json_document", "write_new_bytes", "write_selection"]
