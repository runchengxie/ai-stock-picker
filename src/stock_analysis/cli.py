"""Compatibility module for ``python -m stock_analysis.cli``."""

from .app.cli import app

__all__ = ["app"]

if __name__ == "__main__":
    app()
