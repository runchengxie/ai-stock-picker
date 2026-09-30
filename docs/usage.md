# Usage: from a dry run to a saved result

English · [简体中文](zh-CN/usage.md)

Complete the installation and no-key sample in the [README](../README.md) first.

A real run needs a candidate file, the market's API key, and an unused output path. It contacts a model service and may incur API charges.

## Choose your options

| Option | Purpose | Example |
| --- | --- | --- |
| `--candidates` | Your prepared candidate file | `examples/cn_candidates.json` |
| `--as-of` | Signal date; not automatically today's date | `2026-06-30` |
| `--top-n` | Selection count, no larger than the pool | Use `1` for the A-share sample |
| `--style` | Ranking preference | CN: `momentum` / `quality`; US: `quality` / `growth` |
| `--output` | Where to save the checked result | `$HOME/data/ai-stock-picker/selection.json` |
| `--dry-run` | Check input and show a plan summary | No key or model call |

The samples are historical inputs for learning the commands. For research, prepare a pool corresponding to the signal date; changing only the date to today does not refresh the data. The A-share sample contains one stock, so it checks the workflow rather than demonstrating a multi-stock ranking.

## A-shares: DeepSeek

The standard A-share command reads only `DEEPSEEK_API_KEY`. Replace the placeholder paths with your files; a `--top-n 10` example needs at least 10 candidates.

```bash
export DEEPSEEK_API_KEY='YOUR_DEEPSEEK_API_KEY'
uv run aipick cn pick \
  --candidates /absolute/path/cn_candidates.json \
  --output /absolute/path/cn_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-flash \
  --thinking disabled \
  --max-tokens 8192
```

The default is `deepseek-v4-flash` with thinking explicitly disabled. With thinking enabled, choose `high` or `max`; the request then omits `temperature`. `max_tokens` must be between 1 and 65,536.

```bash
uv run aipick cn pick \
  --candidates /absolute/path/cn_candidates.json \
  --output /absolute/path/cn_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-pro \
  --thinking enabled \
  --reasoning-effort max \
  --max-tokens 32768
```

For repeatable batch runs, `pick-plan` freezes the pool, Prompt, presentation order, model, and inference options without reading credentials or using the network. Execute its `plan.json` with `trial`; frozen options cannot be overridden. Anonymous controls require both complete symbol and name mappings, and the full frozen Prompt must contain no real symbols or names. See [Evidence and stability](evidence-and-stability.md).

## US stocks: Gemini

The US command reads only `GEMINI_API_KEY`:

```bash
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'
uv run aipick us pick \
  --candidates /absolute/path/us_candidates.json \
  --output /absolute/path/us_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style quality
```

## Use a credential file

For cross-repository calls, use `--credential-file /absolute/path/api_keys.json`. The file must be owned by the current user, have permissions exactly `0600`, and be no larger than 128 KiB. Prefer this JSON structure; literal UTF-8 `KEY=value` lines remain supported.

```json
{
  "ai_stock_picker": {
    "deepseek": {"api_key": "YOUR_DEEPSEEK_API_KEY"},
    "gemini": {"api_key": "YOUR_GEMINI_API_KEY"}
  }
}
```

The parser does not execute a shell or expand variables. It returns only the active provider's key. Duplicate JSON keys, invalid types, and empty keys are rejected. Environment variables are read only when `--credential-file` is omitted.

Keep credentials outside source repositories. Use your existing private configuration layout, not a copy in the checkout.

## Find your results

A real run creates both a result file and an append-only evidence directory. Without `--evidence-dir`, the directory is `<output>.evidence`. Neither may already exist.

Evidence includes the original pool, numeric ranking, exact Prompt, sanitized HTTP information and request body, raw response, requested and actual model identities, extracted text, selection, and file hashes. Credentials are excluded. An HTTP success with an invalid response is archived as rejected evidence and does not produce a result file.

The manifest separates transport, ranking, and publication checks. If ranking passes but commentary fails, the run stays `rejected` and saves `ranking_diagnostic.json` containing the stock order. This research diagnostic never substitutes for a published `selection.json`.

`reasoning` and `risk_note` are AI interpretations of candidate fields, not independently checked facts or investment advice. Approved natural-language labels can identify candidate fields; current production commentary has additional exact numeric-reference requirements described in [Output format](output-artifact.md).

## Common errors

| Problem | What to do |
| --- | --- |
| `uv` is not found | Follow the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/), then reopen your terminal |
| Too few candidates | Lower `--top-n` or provide a larger pool |
| Date validation fails | Compare `--as-of` with the pool's observation date; see [Input formats](input-formats.md) |
| API key is missing | Set the market-specific environment variable or provide a secure credential file |
| Output or evidence path already exists | Choose an unused path; existing results are preserved |
| Model response is rejected | Inspect the error and evidence directory; rejected output is not published |

For controlled experiments, see the [Research guide](shadow-research.md). For checks and contributions, see [Development](development.md).
