"""Backward-compatible CLI entrypoint."""

from .app.cli import *  # noqa: F401,F403


if __name__ == "__main__":
    app()
