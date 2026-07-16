"""Securely load one provider-specific API key from a credentials file."""

from __future__ import annotations

import json
import os
import re
import stat
from typing import Any

from stock_analysis.ai_lab.contracts import Provider

MAX_CREDENTIAL_FILE_BYTES = 128 * 1024

_PROVIDER_KEYS: dict[Provider, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
_JSON_NAMESPACE = "ai_stock_picker"
_KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_READ_CHUNK_BYTES = 16 * 1024


class CredentialFileError(RuntimeError):
    """A sanitized credentials-file validation or parsing failure."""


def load_provider_api_key(
    provider: Provider,
    path: str | os.PathLike[str],
) -> str:
    """Return only the API key assigned to ``provider`` in a secure file.

    The file may be a strict JSON credential registry or the legacy format that
    is deliberately smaller than dotenv or shell syntax. JSON uses
    ``ai_stock_picker.<provider>.api_key``. Legacy blank lines and whole-line
    comments are ignored, and all other useful lines are literal ``KEY=value``
    assignments. Values are never expanded or executed.
    """

    try:
        requested_key = _PROVIDER_KEYS[provider]
    except KeyError:
        raise CredentialFileError("unsupported credential provider") from None

    descriptor = _open_securely(path)
    try:
        initial = os.fstat(descriptor)
        _validate_file_metadata(initial)
        payload = _bounded_read(descriptor)
        final = os.fstat(descriptor)
        _validate_file_metadata(final)
        if _file_snapshot(initial) != _file_snapshot(final):
            raise CredentialFileError("credential file changed while reading")
    except OSError:
        raise CredentialFileError(
            "credential file could not be read securely"
        ) from None
    finally:
        os.close(descriptor)
    return _parse_requested_credential(payload, provider, requested_key)


def _open_securely(path: str | os.PathLike[str]) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags |= nofollow

    before: os.stat_result | None = None
    if not nofollow:
        try:
            before = os.lstat(path)
        except OSError:
            raise CredentialFileError(
                "credential file could not be opened securely"
            ) from None
        if stat.S_ISLNK(before.st_mode):
            raise CredentialFileError("credential file could not be opened securely")

    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise CredentialFileError(
            "credential file could not be opened securely"
        ) from None

    if before is not None:
        try:
            after = os.fstat(descriptor)
        except OSError:
            os.close(descriptor)
            raise CredentialFileError(
                "credential file could not be opened securely"
            ) from None
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            os.close(descriptor)
            raise CredentialFileError("credential file changed while opening")
    return descriptor


def _validate_file_metadata(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise CredentialFileError("credential file must be a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise CredentialFileError("credential file must have exact mode 0600")
    if _owner_check_supported() and metadata.st_uid != os.geteuid():
        raise CredentialFileError("credential file must be owned by the current user")
    if metadata.st_size > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialFileError("credential file exceeds the 128 KiB limit")


def _owner_check_supported() -> bool:
    return hasattr(os, "geteuid")


def _file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return the metadata that must remain stable for the entire read."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _bounded_read(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_CREDENTIAL_FILE_BYTES:
        limit = min(_READ_CHUNK_BYTES, MAX_CREDENTIAL_FILE_BYTES + 1 - size)
        chunk = os.read(descriptor, limit)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    if size > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialFileError("credential file exceeds the 128 KiB limit")
    return b"".join(chunks)


def _parse_requested_credential(
    payload: bytes,
    provider: Provider,
    requested_key: str,
) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise CredentialFileError("credential file must be valid UTF-8") from None

    if text.lstrip().startswith("{"):
        return _parse_json_assignment(text, provider)
    return _parse_requested_assignment(text, requested_key)


class _DuplicateJsonKey(ValueError):
    """Internal signal for duplicate JSON object members."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _parse_json_assignment(text: str, provider: Provider) -> str:
    try:
        payload = json.loads(text, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, _DuplicateJsonKey):
        raise CredentialFileError("credential JSON is invalid") from None
    if not isinstance(payload, dict):
        raise CredentialFileError("credential JSON root must be an object")

    namespace = payload.get(_JSON_NAMESPACE)
    if namespace is None:
        raise CredentialFileError(f"{_JSON_NAMESPACE} credential section is missing")
    if not isinstance(namespace, dict):
        raise CredentialFileError(
            f"{_JSON_NAMESPACE} credential section must be an object"
        )

    provider_config = namespace.get(provider)
    if provider_config is None:
        raise CredentialFileError(f"{_JSON_NAMESPACE}.{provider} credential is missing")
    if not isinstance(provider_config, dict):
        raise CredentialFileError(
            f"{_JSON_NAMESPACE}.{provider} credential must be an object"
        )

    value = provider_config.get("api_key")
    if value is None:
        raise CredentialFileError(f"{_JSON_NAMESPACE}.{provider}.api_key is missing")
    if not isinstance(value, str):
        raise CredentialFileError(
            f"{_JSON_NAMESPACE}.{provider}.api_key must be a string"
        )
    if not value.strip():
        raise CredentialFileError(f"{_JSON_NAMESPACE}.{provider}.api_key is empty")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise CredentialFileError(f"{_JSON_NAMESPACE}.{provider}.api_key is malformed")
    return value


def _parse_requested_assignment(text: str, requested_key: str) -> str:
    found: str | None = None
    for raw_line in text.split("\n"):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator and _KEY_NAME.fullmatch(name):
            if name != requested_key:
                continue
            if found is not None:
                raise CredentialFileError(f"duplicate {requested_key} assignment")
            if not value.strip():
                raise CredentialFileError(f"{requested_key} assignment is empty")
            if "\x00" in value or "\r" in value:
                raise CredentialFileError(f"malformed {requested_key} assignment")
            found = value
        elif _looks_like_requested_assignment(line, requested_key):
            raise CredentialFileError(f"malformed {requested_key} assignment")

    if found is None:
        raise CredentialFileError(f"{requested_key} assignment is missing")
    return found


def _looks_like_requested_assignment(line: str, requested_key: str) -> bool:
    stripped = line.lstrip()
    prefix = re.compile(
        rf"^(?:export[ \t]+)?{re.escape(requested_key)}(?:[ \t]*:?=|[ \t]+|$)"
    )
    return prefix.match(stripped) is not None


__all__ = [
    "CredentialFileError",
    "MAX_CREDENTIAL_FILE_BYTES",
    "load_provider_api_key",
]
