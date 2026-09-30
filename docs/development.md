# Development and checks

English · [简体中文](zh-CN/development.md)

## Environment

Use Python 3.10–3.12 and `uv`. Install locked development dependencies:

```bash
uv sync --locked --group dev
```

For runtime dependencies only:

```bash
uv sync --locked --no-dev
```

## One quality entry point

```bash
uv run python scripts/dev/check.py
```

The script runs, in order:

1. `uv lock --check`
2. `ruff check .`
3. `ruff format --check .`
4. `ty check`
5. `pytest`
6. Maintainability ratchet
7. Wheel and sdist build

It stops at the first failure and returns that exit code. The project has no pre-commit configuration or Makefile. GitHub Actions `ci.yml` calls this same entry point; avoid duplicating the check commands into another quality workflow. `pages.yml` separately validates and publishes the website; see [Website maintenance](showcase.md).

## Ruff

```bash
uv run ruff check .
uv run ruff format --check .
```

To format or apply safe lint fixes:

```bash
uv run ruff format .
uv run ruff check . --fix
```

Style: Python 3.10 syntax minimum, 88-character lines, double quotes, and four-space indentation.

## ty

```bash
uv run ty check
```

The target Python version is 3.10 and checked roots are `src`, `scripts`, and `tests`. ty is beta, so it is pinned to an explicit version. Upgrade it together with the lockfile and run the full gate to identify changed diagnostics. It is the sole required type checker.

Compatibility settings are narrowly scoped:

- Allow `tomli`/`tomllib` fallback imports across Python versions.
- In `tests/test_selection.py`, allow intentional invalid-Literal arguments and mutation of frozen models in negative tests.

No corresponding diagnostics are disabled globally. Prefer removing overrides when the affected code changes; explain the triggering case and removal plan in a PR before adding one.

## Tests

Default tests enforce 75% coverage with branch measurement:

```bash
uv run pytest
```

Run one file or one case:

```bash
uv run pytest tests/test_cli.py
uv run pytest tests/test_cli.py::test_dry_run_is_network_free_and_reports_hashes
```

Tests must not contact real providers. Inject a caller, transport, or monkeypatch.

## Maintainability

```bash
uv run python scripts/dev/maintainability_metrics.py --ratchet
```

The ratchet checks lines over 100 characters; functions over 100, 250, or 500 lines; file-level `C901` ignores; files over 800 or 1,200 lines; and test files over 1,000 lines. Budgets should only tighten. Explain any relaxation in the PR.

## Packaging

```bash
uv run python -m build
```

Check the wheel in a temporary environment:

```bash
uv venv /tmp/aipick-wheel
uv pip install --python /tmp/aipick-wheel/bin/python dist/*.whl
cd /tmp
/tmp/aipick-wheel/bin/aipick --help
```

The CLI must work outside the repository directory. Runtime code must not depend on implicit root-level configuration or data files.

## Dependency changes

After editing `pyproject.toml`:

```bash
uv lock
uv sync --locked --group dev
uv run python scripts/dev/check.py
```

Commit both `pyproject.toml` and `uv.lock`.

## Before submitting

Run the full quality entry point. For CLI, input contracts, output schemas, providers, or atomic persistence changes, also exercise relevant dry-run commands and verify that error paths do not write files.

Update English and Chinese reference documentation together. Keep commands, field names, internal identifiers, and persisted values stable across languages.
