"""Path confinement shared by append-only artifact bundles."""

from __future__ import annotations

from pathlib import Path


def safe_bundle_path(root: Path, relative: str, *, label: str) -> Path:
    """Resolve a bundle path after rejecting traversal and every symlink hop."""

    if not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} paths must be non-empty and relative")
    unresolved = root / relative
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise ValueError(f"{label} path contains a symlink")
        current = current.parent
    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"{label} path escapes its bundle directory")
    return candidate


def reject_symlink_path(path: Path, *, label: str) -> None:
    """Reject a supplied path when it or any existing parent is a symlink."""

    current = path
    while True:
        if current.is_symlink():
            raise ValueError(f"{label} path must not contain a symlink")
        if current == current.parent:
            return
        current = current.parent


__all__ = ["reject_symlink_path", "safe_bundle_path"]
