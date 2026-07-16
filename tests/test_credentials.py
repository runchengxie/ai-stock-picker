from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from stock_analysis.ai_lab import credentials
from stock_analysis.ai_lab.contracts import Provider
from stock_analysis.ai_lab.credentials import (
    CredentialFileError,
    load_provider_api_key,
)


def _write_credentials(path: Path, text: str | bytes, *, mode: int = 0o600) -> Path:
    payload = text.encode() if isinstance(text, str) else text
    path.write_bytes(payload)
    path.chmod(mode)
    return path


@pytest.mark.parametrize(
    ("provider", "variable", "value"),
    [
        ("deepseek", "DEEPSEEK_API_KEY", "deepseek-secret"),
        ("gemini", "GEMINI_API_KEY", "gemini-secret"),
    ],
)
def test_loads_only_requested_provider_key(
    tmp_path: Path,
    provider: Provider,
    variable: str,
    value: str,
) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        (f"# provider credentials\nUNRELATED=value\n{variable}={value}\n"),
    )

    assert load_provider_api_key(provider, path) == value


@pytest.mark.parametrize(
    ("provider", "value"),
    [
        ("deepseek", "deepseek-json-secret"),
        ("gemini", "gemini-json-secret"),
    ],
)
def test_loads_requested_provider_from_namespaced_json(
    tmp_path: Path,
    provider: Provider,
    value: str,
) -> None:
    path = _write_credentials(
        tmp_path / "api_keys.json",
        (
            "{\n"
            '  "unrelated": "ignored",\n'
            '  "ai_stock_picker": {\n'
            '    "deepseek": {"api_key": "deepseek-json-secret"},\n'
            '    "gemini": {"api_key": "gemini-json-secret"}\n'
            "  }\n"
            "}\n"
        ),
    )

    assert load_provider_api_key(provider, path) == value


def test_json_provider_isolation_does_not_fallback_to_sibling(tmp_path: Path) -> None:
    path = _write_credentials(
        tmp_path / "api_keys.json",
        '{"ai_stock_picker":{"gemini":{"api_key":"gemini-only"}}}\n',
    )

    with pytest.raises(
        CredentialFileError, match=r"ai_stock_picker\.deepseek.*missing"
    ):
        load_provider_api_key("deepseek", path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{}", "section is missing"),
        ('{"ai_stock_picker":[]}', "section must be an object"),
        ('{"ai_stock_picker":{"deepseek":[]}}', "credential must be an object"),
        ('{"ai_stock_picker":{"deepseek":{}}}', "api_key is missing"),
        ('{"ai_stock_picker":{"deepseek":{"api_key":null}}}', "api_key is missing"),
        ('{"ai_stock_picker":{"deepseek":{"api_key":1}}}', "api_key must be a string"),
        ('{"ai_stock_picker":{"deepseek":{"api_key":"  "}}}', "api_key is empty"),
        (
            '{"ai_stock_picker":{"deepseek":{"api_key":"bad\\nkey"}}}',
            "api_key is malformed",
        ),
        ('{"ai_stock_picker":', "credential JSON is invalid"),
        (
            '{"ai_stock_picker":{"deepseek":{"api_key":"first","api_key":"second"}}}',
            "credential JSON is invalid",
        ),
    ],
)
def test_rejects_invalid_json_credentials(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = _write_credentials(tmp_path / "api_keys.json", content)

    with pytest.raises(CredentialFileError, match=message):
        load_provider_api_key("deepseek", path)


def test_cross_provider_assignment_is_not_a_fallback(tmp_path: Path) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        "GEMINI_API_KEY=gemini-only\n",
    )

    with pytest.raises(CredentialFileError, match="DEEPSEEK_API_KEY.*missing"):
        load_provider_api_key("deepseek", path)


def test_unrequested_key_is_not_parsed_or_retained(tmp_path: Path) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        "export GEMINI_API_KEY=malformed-other-key\nDEEPSEEK_API_KEY=chosen\n",
    )

    assert load_provider_api_key("deepseek", path) == "chosen"


def test_shell_syntax_is_returned_literally_and_never_executed(tmp_path: Path) -> None:
    side_effect = tmp_path / "must-not-exist"
    literal = f"$(touch {side_effect})"
    path = _write_credentials(
        tmp_path / "credentials.env",
        f"DEEPSEEK_API_KEY={literal}\n",
    )

    assert load_provider_api_key("deepseek", path) == literal
    assert not side_effect.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("OTHER=value\n", "missing"),
        ("DEEPSEEK_API_KEY=\n", "empty"),
        ("DEEPSEEK_API_KEY=   \n", "empty"),
        ("DEEPSEEK_API_KEY\n", "malformed"),
        ("export DEEPSEEK_API_KEY=value\n", "malformed"),
        (" DEEPSEEK_API_KEY=value\n", "malformed"),
        ("DEEPSEEK_API_KEY =value\n", "malformed"),
        ("DEEPSEEK_API_KEY=value\nDEEPSEEK_API_KEY=again\n", "duplicate"),
    ],
)
def test_rejects_missing_empty_duplicate_or_malformed_requested_assignment(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = _write_credentials(tmp_path / "credentials.env", content)

    with pytest.raises(CredentialFileError, match=message):
        load_provider_api_key("deepseek", path)


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o660, 0o700])
def test_requires_exact_mode_0600(tmp_path: Path, mode: int) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        "DEEPSEEK_API_KEY=secret\n",
        mode=mode,
    )

    with pytest.raises(CredentialFileError, match="exact mode 0600"):
        load_provider_api_key("deepseek", path)


def test_rejects_symlink_even_when_target_is_secure(tmp_path: Path) -> None:
    target = _write_credentials(
        tmp_path / "target.env",
        "DEEPSEEK_API_KEY=secret\n",
    )
    link = tmp_path / "credentials.env"
    link.symlink_to(target)

    with pytest.raises(CredentialFileError, match="opened securely"):
        load_provider_api_key("deepseek", link)


def test_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)

    with pytest.raises(CredentialFileError, match="regular file"):
        load_provider_api_key("deepseek", directory)


def test_rejects_file_larger_than_128_kib(tmp_path: Path) -> None:
    payload = b"DEEPSEEK_API_KEY=" + b"x" * credentials.MAX_CREDENTIAL_FILE_BYTES
    path = _write_credentials(tmp_path / "credentials.env", payload)

    with pytest.raises(CredentialFileError, match="128 KiB"):
        load_provider_api_key("deepseek", path)


def test_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        b"DEEPSEEK_API_KEY=secret\xff\n",
    )

    with pytest.raises(CredentialFileError, match="valid UTF-8"):
        load_provider_api_key("deepseek", path)


def test_rejects_file_not_owned_by_current_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not hasattr(os, "geteuid"):
        return
    path = _write_credentials(
        tmp_path / "credentials.env",
        "DEEPSEEK_API_KEY=secret\n",
    )
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)

    with pytest.raises(CredentialFileError, match="current user"):
        load_provider_api_key("deepseek", path)


def test_rejects_path_replacement_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        "DEEPSEEK_API_KEY=original\n",
    )
    replacement = _write_credentials(
        tmp_path / "replacement.env",
        "DEEPSEEK_API_KEY=replacement\n",
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
        load_provider_api_key("deepseek", path)
    assert path.read_text(encoding="utf-8").endswith("replacement\n")


def test_rejects_same_inode_modified_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_credentials(
        tmp_path / "credentials.env",
        "DEEPSEEK_API_KEY=original\n",
    )
    initial = path.stat()
    real_read = os.read
    modified = False

    def modifying_read(descriptor: int, size: int) -> bytes:
        nonlocal modified
        if not modified:
            modified = True
            path.write_text(
                "DEEPSEEK_API_KEY=MODIFIED\n",
                encoding="utf-8",
            )
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
        load_provider_api_key("deepseek", path)


def test_open_uses_nofollow_when_platform_supports_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not getattr(os, "O_NOFOLLOW", 0):
        return
    path = _write_credentials(
        tmp_path / "credentials.env",
        "DEEPSEEK_API_KEY=secret\n",
    )
    real_open = os.open
    observed_flags: list[int] = []

    def recording_open(open_path: str | os.PathLike[str], flags: int) -> int:
        observed_flags.append(flags)
        return real_open(open_path, flags)

    monkeypatch.setattr(os, "open", recording_open)

    assert load_provider_api_key("deepseek", path) == "secret"
    assert observed_flags[0] & os.O_NOFOLLOW


def test_errors_do_not_disclose_path_or_file_contents(tmp_path: Path) -> None:
    secret_path_fragment = "path-containing-secret"
    secret_value = "value-containing-secret"
    path = _write_credentials(
        tmp_path / secret_path_fragment,
        f"DEEPSEEK_API_KEY={secret_value}\n",
        mode=0o644,
    )

    with pytest.raises(CredentialFileError) as error:
        load_provider_api_key("deepseek", path)

    message = str(error.value)
    assert secret_path_fragment not in message
    assert secret_value not in message


def test_rejects_unknown_provider_without_opening_file(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist"

    with pytest.raises(CredentialFileError, match="unsupported"):
        load_provider_api_key(cast(Provider, "other"), path)
