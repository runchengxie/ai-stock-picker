"""Shared command result utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    """Normalized response from CLI command handlers."""

    exit_code: int
    stdout: str | None = None
    stderr: str | None = None
    rich_renderable: object | None = None

    def as_tuple(self) -> tuple[int, str | None, str | None]:
        """Return a tuple representation for convenience."""

        return self.exit_code, self.stdout, self.stderr
