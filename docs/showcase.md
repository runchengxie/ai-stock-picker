# Website and automated publishing

English · [简体中文](zh-CN/showcase.md)

The [project website](https://runchengxie.github.io/ai-stock-picker/) introduces the tool and links to guides. It is a static page, not a live stock dashboard. It makes no provider calls and requires no API keys.

## Files

- `site/index.html`: semantic page structure and complete English fallback content.
- `site/styles.css`: responsive layout, visible keyboard focus, and reduced-motion support.
- `site/app.js`: locale loading, language selection, and localized documentation links.
- `site/locales/en.json` and `zh-CN.json`: human-facing copy under stable semantic keys.
- `.github/workflows/pages.yml`: asset validation and Pages publication.

## Preview locally

From the repository root:

```bash
python -m http.server 8000 --directory site --bind 127.0.0.1
```

Open `http://localhost:8000`. Use an HTTP server because locale catalogs are loaded with `fetch`; opening the HTML directly as a file is not supported for language switching.

## Languages

English is the default and authoritative version. The selector offers Simplified Chinese and remembers the explicit choice when browser storage is available. Missing translated messages fall back to English. If catalogs cannot load, the complete English HTML stays usable. Documentation links follow the selected locale.

Keep translatable copy in locale catalogs; do not embed Chinese strings in components or change JSON field names by locale. When editing English copy, also update the fallback text in `index.html` and the Chinese catalog. The page contains no dynamic financial values or timestamps requiring locale formatting.

Primary documentation lives in `README.md` and `docs/*.md`. Chinese references live in `docs/zh-CN/`; `README-project.md` is the translated project README, and `README.md` is the translated documentation index. The sample guide is paired with `docs/zh-CN/examples.md`. Each document links to its counterpart. Preserve CLI options and protocol values across translations; market-specific A-share commentary remains Chinese even in English documentation.

## Publish with Actions

In repository Settings → Pages, select **GitHub Actions** as the source. No custom domain or repository secret is needed for the static page.

The Pages workflow validates JavaScript syntax and JSON catalogs on relevant pull requests. On changes to `site/**` or its workflow merged into `main`, it uploads **only `site/`** and deploys to the `github-pages` environment. Manual dispatch from `main` also works. Pull requests and other branches cannot deploy. Deployment has narrowly scoped `pages: write` and `id-token: write` permissions; normal validation has only `contents: read`.

The implementation follows [GitHub's custom workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Python quality checks stay in the existing CI workflow using `scripts/dev/check.py`.

## Verify a change

```bash
node --check site/app.js
python -m json.tool site/locales/en.json > /dev/null
python -m json.tool site/locales/zh-CN.json > /dev/null
```

Also inspect desktop and mobile layouts, switch languages, reload to check persistence, follow documentation links, and verify that blocked storage or failed catalog requests leave the page readable. After merging, confirm the Pages workflow succeeded and the public URL serves the updated content.
