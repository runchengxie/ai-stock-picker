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


def test_rejects_path_replacement_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_credentials(
        tmp_path / "credentials.env",
        "CUSTOM_MODEL_API_KEY=original\n",
    )
    replacement = write_credentials(
        tmp_path / "replacement.env",
        "CUSTOM_MODEL_API_KEY=replacement\n",
    )
    real_fstat = os.fstat
    call_count = 0

    def replacing_fstat(descriptor: int) -> os.stat_result:
        nonlocal call_count
        metadata = real_fstat(descriptor)
        call_count += 1
        if call_count == 1:
            replacement.replace(path)
        return metadata

    monkeypatch.setattr(os, "fstat", replacing_fstat)

    with pytest.raises(CredentialFileError, match="changed while reading"):
        load_api_key("CUSTOM_MODEL_API_KEY", path)
    assert path.read_text(encoding="utf-8").endswith("replacement\n")


def test_rejects_same_inode_modified_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_credentials(
        tmp_path / "credentials.env",
        "CUSTOM_MODEL_API_KEY=original\n",
    )
    initial = path.stat()
    real_read = os.read
    modified = False

    def modifying_read(descriptor: int, size: int) -> bytes:
        nonlocal modified
        if not modified:
            modified = True
            path.write_text("CUSTOM_MODEL_API_KEY=MODIFIED\n", encoding="utf-8")
            os.utime(
                path,
                ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000_000),
            )
            current = path.stat()
            assert (current.st_dev, current.st_ino, current.st_size) == (
                initial.st_dev,
                initial.st_ino,
                initial.st_size,
            )
        return real_read(descriptor, size)

    monkeypatch.setattr(os, "read", modifying_read)

    with pytest.raises(CredentialFileError, match="changed while reading"):
        load_api_key("CUSTOM_MODEL_API_KEY", path)


def test_open_uses_nofollow_when_platform_supports_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not getattr(os, "O_NOFOLLOW", 0):
        return
    path = write_credentials(
        tmp_path / "credentials.env",
        "CUSTOM_MODEL_API_KEY=secret\n",
    )
    real_open = os.open
    observed_flags: list[int] = []

    def recording_open(open_path: str | os.PathLike[str], flags: int) -> int:
        observed_flags.append(flags)
        return real_open(open_path, flags)

    monkeypatch.setattr(os, "open", recording_open)

    assert load_api_key("CUSTOM_MODEL_API_KEY", path) == "secret"
    assert observed_flags[0] & os.O_NOFOLLOW
