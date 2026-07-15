from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_stock_picker.credentials import CredentialFileError, load_api_key


def write_credentials(path: Path, content: str | bytes, mode: int = 0o600) -> Path:
    payload = content.encode() if isinstance(content, str) else content
    path.write_bytes(payload)
    path.chmod(mode)
    return path


def test_loads_only_requested_key(tmp_path: Path) -> None:
    path = write_credentials(
        tmp_path / "credentials.env",
        "OTHER=value\nCUSTOM_MODEL_API_KEY=chosen\n",
    )
    assert load_api_key("CUSTOM_MODEL_API_KEY", path) == "chosen"


def test_shell_syntax_is_literal(tmp_path: Path) -> None:
    side_effect = tmp_path / "must-not-exist"
    literal = f"$(touch {side_effect})"
    path = write_credentials(
        tmp_path / "credentials.env",
        f"CUSTOM_MODEL_API_KEY={literal}\n",
    )
    assert load_api_key("CUSTOM_MODEL_API_KEY", path) == literal
    assert not side_effect.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("OTHER=value\n", "missing"),
        ("CUSTOM_MODEL_API_KEY=\n", "empty"),
        ("export CUSTOM_MODEL_API_KEY=value\n", "malformed"),
        (
            "CUSTOM_MODEL_API_KEY=value\nCUSTOM_MODEL_API_KEY=again\n",
            "duplicate",
        ),
    ],
)
def test_rejects_bad_requested_assignment(
    tmp_path: Path, content: str, message: str
) -> None:
    path = write_credentials(tmp_path / "credentials.env", content)
    with pytest.raises(CredentialFileError, match=message):
        load_api_key("CUSTOM_MODEL_API_KEY", path)


def test_requires_exact_mode_and_regular_file(tmp_path: Path) -> None:
    path = write_credentials(
        tmp_path / "credentials.env",
        "CUSTOM_MODEL_API_KEY=secret\n",
        mode=0o644,
    )
    with pytest.raises(CredentialFileError, match="exact mode 0600"):
        load_api_key("CUSTOM_MODEL_API_KEY", path)
    directory = tmp_path / "directory"
    directory.mkdir(mode=0o700)
    with pytest.raises(CredentialFileError, match="regular file"):
        load_api_key("CUSTOM_MODEL_API_KEY", directory)


def test_rejects_symlink(tmp_path: Path) -> None:
    target = write_credentials(
        tmp_path / "target.env",
        "CUSTOM_MODEL_API_KEY=secret\n",
    )
    link = tmp_path / "credentials.env"
    link.symlink_to(target)
    with pytest.raises(CredentialFileError, match="opened securely"):
        load_api_key("CUSTOM_MODEL_API_KEY", link)


def test_rejects_invalid_utf8_and_oversized_file(tmp_path: Path) -> None:
    invalid = write_credentials(
        tmp_path / "invalid.env",
        b"CUSTOM_MODEL_API_KEY=secret\xff\n",
    )
    with pytest.raises(CredentialFileError, match="valid UTF-8"):
        load_api_key("CUSTOM_MODEL_API_KEY", invalid)
    oversized = write_credentials(
        tmp_path / "large.env",
        b"CUSTOM_MODEL_API_KEY=" + b"x" * (128 * 1024),
    )
    with pytest.raises(CredentialFileError, match="128 KiB"):
        load_api_key("CUSTOM_MODEL_API_KEY", oversized)


def test_errors_do_not_disclose_path_or_contents(tmp_path: Path) -> None:
    path = write_credentials(
        tmp_path / "path-containing-secret",
        "CUSTOM_MODEL_API_KEY=value-containing-secret\n",
        mode=0o644,
    )
    with pytest.raises(CredentialFileError) as error:
        load_api_key("CUSTOM_MODEL_API_KEY", path)
    message = str(error.value)
    assert "path-containing-secret" not in message
    assert "value-containing-secret" not in message


def test_rejects_invalid_key_name_without_opening_file(tmp_path: Path) -> None:
    with pytest.raises(CredentialFileError, match="invalid"):
        load_api_key("bad-key", tmp_path / "missing")


def test_owner_check_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, "geteuid"):
        return
    path = write_credentials(
        tmp_path / "credentials.env",
        "CUSTOM_MODEL_API_KEY=secret\n",
    )
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(CredentialFileError, match="current user"):
        load_api_key("CUSTOM_MODEL_API_KEY", path)
