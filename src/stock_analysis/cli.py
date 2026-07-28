"""Compatibility module for ``python -m stock_analysis.cli``.

兼容转发层：仅转发到 ``src/stock_analysis/app/cli.py`` 的真实实现，自身不含逻辑。
保留用于历史入口兼容，未来可移除。
"""

from .app.cli import app

__all__ = ["app"]

if __name__ == "__main__":
    app()
