# Research website: preview and update

English · [简体中文](zh-CN/showcase.md)

The [website](https://runchengxie.github.io/ai-stock-picker/) leads with research findings. The tool introduction and installation walkthrough are on `tool.html`. Neither page calls a model or needs an API key.

## What the website shows

Five archived studies cover input-order stability, Flash/Pro comparison, a six-month rule replay, revised numeric rules, and lower-turnover portfolios. Daily observations are a separate section. The reviewed October 1, 2026 snapshot has no verified continuous daily series; the July 18 offline rehearsal is clearly separated.

Holding-period controls compare matched historical results. Model tests keep ranking validity separate from complete-result usability. Missing returns are not zeros, failed runs stay visible, and no daily-return curve is fabricated. Plain-language explanations are in [Research notes](research/README.md).

## Where the numbers live

Generated snapshots and preview builds stay outside the source repository. `site/research-source.json` records a release tag and SHA-256 for the reviewed `research.json` asset. Actions downloads that exact asset, checks its digest and evidence classification, then stages the site under the runner's temporary directory.

The snapshot is a public aggregate, not a copy of private raw responses. It contains reviewed numbers and source filenames/content hashes. Original reports and receipts stay in the private owner's research archive. A source hash identifies bytes; it is not an independent historical timestamp. Asset pinning makes a silent release-asset change fail the build.

## Preview locally

Download the pinned asset into your data directory, then build into a new path outside the checkout:

```bash
mkdir -p "$HOME/data/ai-stock-picker/research-site/download"
gh release download research-data-2026-10-01 \
  --repo runchengxie/ai-stock-picker \
  --pattern research.json \
  --dir "$HOME/data/ai-stock-picker/research-site/download"
python scripts/site/build.py \
  --snapshot "$HOME/data/ai-stock-picker/research-site/download/research.json" \
  --output "$HOME/data/ai-stock-picker/research-site/preview"
python -m http.server 8000 \
  --directory "$HOME/data/ai-stock-picker/research-site/preview" \
  --bind 127.0.0.1
```

Open `http://localhost:8000`. Choose an unused output directory for another build. Existing output is never overwritten. If the release pin changes, use its tag instead of the example tag above.

## Update daily observations

A daily row must come from a real owner day bundle validated by `validate_shadow_day`, not from a caller's self-reported `valid=true`. The importer rejects offline/unbound rehearsals and exports only an allowlisted public summary:

```bash
uv run python scripts/site/export_daily.py \
  --snapshot /absolute/path/research.json \
  --day-dir /absolute/path/campaign/arm/provider--model/YYYY-MM-DD \
  --output "$HOME/data/ai-stock-picker/research-site/next-research.json"
```

Repeat `--day-dir` for additional bundles. Validation includes repetitions, consensus, and frozen launch lineage. Failed terminal states are retained. It does not compute profits or upgrade timing/out-of-sample status.

Review the combined snapshot, reconcile counts and definitions, record a new review date, and publish it as a **new** research-data release asset. Update the release tag and SHA-256 in `site/research-source.json` in a PR. Do not replace the old release asset. Historical study fields are tied to those specific experiments; adding a new experiment requires updating the contract, charts, and notes, not overwriting old findings.

A GitHub runner cannot read the private host's filesystem. Preparing and reviewing a new snapshot happens separately from deployment; the site is not claiming automatic daily data collection.

## Languages and interaction

English is primary. `site/locales/en.json` and `zh-CN.json` hold copy under stable semantic keys. The selected language is remembered when browser storage permits. Documentation links follow it, dates and numbers use the selected locale with an explicit UTC date display, and missing messages fall back to English.

`site/app.js` renders the research views; `research-model.mjs` owns small tested metric/view helpers. `tool.js` maintains the installation subpage. Both use relative asset paths for GitHub project Pages. The generated HTML includes a readable English summary if JavaScript or data loading fails.

Keep English HTML fallback text aligned with the catalogs. Update English and Chinese research notes together. Do not translate CLI options, field names, or persisted identifiers.

## Validation and deployment

Run the existing Python quality gate, including publishing tests:

```bash
uv run python scripts/dev/check.py
node --test tests/site/*.test.mjs
```

Inspect desktop/mobile views, language switching, source details, study and holding-period controls, missing-data states, and the tool subpage. Verify displayed calculations against the snapshot.

Pages Actions runs frontend checks and the real pinned-data build on PRs. It publishes only the staged public site from `main`. Publishing permissions remain scoped to the deploy job, and Python quality checks still use the single existing CI entry point. The design follows [GitHub's Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
