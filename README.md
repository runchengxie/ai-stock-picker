# AI Stock Picker

English · [简体中文](docs/zh-CN/README-project.md)

**Give AI your stock shortlist, select a set number of candidates, and save a checked result.**

For example, you already have 30 candidates and want to select 5 with a quality preference. This tool reads your data, asks a model to rank the candidates, checks that the selection stays within your pool and has the right count, then saves a JSON result and a run record.

[Research results](https://runchengxie.github.io/ai-stock-picker/) · [Usage guide](docs/usage.md) · [All documentation](docs/README.md)

## What it does

| You provide | The tool handles | You receive |
| --- | --- | --- |
| Candidate file, signal date, and selection count | AI ranking → validation → saving | Selected stocks, input-based explanations, and run evidence |

- **China A-shares** use DeepSeek; **US stocks** use Gemini.
- The model can only choose from your candidates. Names and themes come from your input.
- It does not fetch market data, generate candidate pools, backtest, or place orders.

## First run: no API key needed

Install **Python 3.10–3.12** and [uv](https://docs.astral.sh/uv/getting-started/installation/). In your terminal:

```bash
git clone https://github.com/runchengxie/ai-stock-picker.git
cd ai-stock-picker
uv sync --locked --no-dev
```

Check your installation with the bundled A-share sample:

```bash
uv run aipick cn pick \
  --candidates examples/cn_candidates.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

On success, the terminal shows a plan summary, including candidate count, model, and Prompt information. `--dry-run` does not read credentials, call a model, or write a result.

The sample has one candidate and demonstrates the workflow. Its date matches the historical sample; do not change it to today. It is not a current stock recommendation. For the US sample, see [Examples](examples/README.md).

## Generate a real model result

Remove `--dry-run` and supply the market's API key and an output path. This example uses the same historical input. Calling the model may incur API charges.

```bash
export DEEPSEEK_API_KEY='YOUR_DEEPSEEK_API_KEY'
mkdir -p "$HOME/data/ai-stock-picker"
uv run aipick cn pick \
  --candidates examples/cn_candidates.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --output "$HOME/data/ai-stock-picker/cn-selection.json"
```

On success, you receive:

- `cn-selection.json`: the validated selection.
- `cn-selection.json.evidence/`: inputs, Prompt, sanitized requests, raw responses, and validation records.

Existing files and evidence directories are never overwritten. Choose a new output path for another run. Replace the sample with your own candidate pool for your research.

For US commands, model options, secure credential files, and common errors, see the [Usage guide](docs/usage.md).

## What did the experiments find?

The [results page](https://runchengxie.github.io/ai-stock-picker/) compares model reliability, historical rule changes, and turnover. The [plain-language notes](docs/research/README.md) explain each result. The reviewed snapshot does not yet include a verified continuous daily series; an offline rehearsal is shown separately.

## Where to go next

| Your next task | Documentation |
| --- | --- |
| Prepare your own data | [Input formats](docs/input-formats.md) |
| Read the result JSON | [Output format](docs/output-artifact.md) |
| Inspect a run record | [Evidence archives](docs/evidence-and-stability.md) |
| Run repeated or controlled experiments | [Research guide](docs/shadow-research.md) |
| Change the project or run checks | [Development](docs/development.md) |

AI commentary is based only on candidate fields and is not independently fact-checked. Traceable run records do not guarantee returns or prove strict historical timing. Outputs are for research, not investment advice.
