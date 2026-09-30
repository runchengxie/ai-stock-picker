# Example inputs

English · [简体中文](../docs/zh-CN/examples.md)

These bundled files can be used directly for dry runs. They are historical inputs, not current recommendations. Run commands from the repository root.

## A-shares

[`cn_candidates.json`](cn_candidates.json) follows the v1 `hot_sector_candidate_universe` contract and contains one candidate. Use `--top-n 1`. New research campaigns should use v2; this fixture remains for compatibility and installation checks.

```bash
uv run aipick cn pick \
  --candidates examples/cn_candidates.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

## US stocks

[`us_candidates.json`](us_candidates.json) is a generic JSON manifest with two candidates. Use `--top-n 1` or `2`.

```bash
uv run aipick us pick \
  --candidates examples/us_candidates.json \
  --as-of 2026-07-15 \
  --top-n 2 \
  --style quality \
  --dry-run
```

## Why keep these in `examples/`?

They are source-controlled input fixtures for learning formats and checking installation, not generated output. Save generated selections and retained evidence outside the repository in a caller-specified location.

See [Input formats](../docs/input-formats.md) for the field reference.
