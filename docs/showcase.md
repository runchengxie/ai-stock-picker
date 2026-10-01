# Research website: preview and maintain

English · [简体中文](zh-CN/showcase.md)

The [research site](https://runchengxie.github.io/ai-stock-picker/) is the main way to read this project's results. The homepage shows reviewed comparisons; each study has a plain-language note in English and Chinese. The [tool page](https://runchengxie.github.io/ai-stock-picker/tool.html) explains how to install and try the CLI. Both are static pages: they do not call an AI model or need an API key.

## What readers can see

The site covers five archived studies: model stability, Flash versus Pro, two rule replays, and a turnover experiment. It keeps failed checks and missing results visible. The current snapshot has no verified continuous daily series; a July 18 offline rehearsal is labeled separately. Results are historical research, not investment advice or evidence that the tool is ready for live trading.

The pages and note routes are built with Astro 7. English is the default; readers can switch languages and dark mode. The site remembers both choices when browser storage is available. The source notes in `docs/research/` and `docs/zh-CN/research/` are the only copies of the note text; Astro reads them directly and checks that every English note has one Chinese translation.

## Preview the site

Install Node.js 24 and the repository's locked npm dependencies. Download the exact snapshot release pinned in `site/research-source.json`, validate and stage it outside the checkout, then build to a new output directory outside the checkout:

```bash
npm ci
gh release download research-data-2026-10-01 \
  --repo runchengxie/ai-stock-picker \
  --pattern research.json \
  --dir "$HOME/data/ai-stock-picker/research-site/download"
uv run python scripts/site/stage_snapshot.py \
  --snapshot "$HOME/data/ai-stock-picker/research-site/download/research.json" \
  --output "$HOME/data/ai-stock-picker/research-site/research.json"
export AIPICK_RESEARCH_SNAPSHOT="$HOME/data/ai-stock-picker/research-site/research.json"
npm run check
npm run build -- --outDir "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker"
mkdir -p "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker/data"
cp "$AIPICK_RESEARCH_SNAPSHOT" \
  "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker/data/research.json"
AIPICK_SITE_OUTPUT="$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker" \
  node --test tests/site/*.test.mjs
python -m http.server 8000 \
  --directory "$HOME/data/ai-stock-picker/research-site/preview-20261002" \
  --bind 127.0.0.1
```

Open `http://localhost:8000/ai-stock-picker/`. Pick a new preview directory for each build; do not build generated files into the repository. If the release pin changes, use the new tag from `site/research-source.json` instead of the example above.

## How publishing works

The Pages workflow runs on pull requests to check the content, frontend, snapshot, and generated routes. It downloads the pinned release asset, checks its SHA-256 and public-data contract with `scripts/site/stage_snapshot.py`, and builds the static site in the runner's temporary directory. Only a successful build on `main` is deployed.

The public JSON contains reviewed aggregate results and source fingerprints. It does not contain private candidate pools, prompts, raw model responses, or credentials. A source hash identifies the file contents; it does not prove when the source was created. Changing the release tag or digest requires a reviewed PR. Publish new data as a new release asset; do not replace the old one.

To add daily observations, start with a real owner day bundle and use `scripts/site/export_daily.py`. The exporter validates repetitions, consensus, and frozen launch lineage, and only exports fields allowed by the public contract. It does not calculate returns or upgrade the evidence classification. Review the combined snapshot and update the release pin through a PR.

## Checks

Run the Python project checks and frontend/content tests before opening a PR:

```bash
uv run python scripts/dev/check.py
npm ci
npm run check
node --test tests/site/research-model.test.mjs tests/site/research-notes.test.mjs
```

The generated-site test needs a completed Astro build and `AIPICK_SITE_OUTPUT` pointing to it, as shown above. Pages Actions does this automatically. Confirm the rendered results against the snapshot when changing metrics, and keep the English note and its Chinese reference in sync.
