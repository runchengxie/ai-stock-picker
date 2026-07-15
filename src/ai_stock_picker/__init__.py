"""Provider-neutral, auditable model reranking of stock candidate manifests."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-stock-picker")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.2.0"

__all__ = ["__version__"]
