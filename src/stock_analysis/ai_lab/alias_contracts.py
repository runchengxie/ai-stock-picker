"""Canonical byte and digest contracts for candidate identity aliases."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256


def alias_map_bytes(aliases: Mapping[str, str]) -> bytes:
    """Serialize one normalized alias map into stable UTF-8 JSON bytes."""

    return _json_bytes(dict(aliases))


def alias_maps_sha256(
    symbol_aliases: Mapping[str, str],
    name_aliases: Mapping[str, str],
) -> str | None:
    """Bind both normalized alias maps with one SHA-256 digest."""

    if not symbol_aliases and not name_aliases:
        return None
    payload = _json_bytes(
        {
            "symbol_aliases": dict(symbol_aliases),
            "name_aliases": dict(name_aliases),
        }
    )
    return sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


__all__ = ["alias_map_bytes", "alias_maps_sha256"]
