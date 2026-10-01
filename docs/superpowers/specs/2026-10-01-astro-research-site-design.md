# Astro research site design

## Goal

Make the AI Stock Picker website the primary place to read the research results and their experiment notes. Keep the site static and deploy it to the existing GitHub Pages URL. Keep the Python command-line tool and its research data contracts independent of the web framework.

## Agreed direction

Use Astro for all reader-facing pages: the research-results homepage, the tool introduction at the existing `/tool.html` path, and individual research notes. Keep the current site URL and the existing Pages deployment workflow. Keep the Python package, selection logic, model integrations, pinned research release, and metric definitions unchanged.

Astro is a good fit because most pages are articles and research summaries. Its content collections can validate the shape of the bilingual Markdown notes at build time. Astro's static output fits GitHub Pages; small browser scripts will continue to handle chart filters, language selection, and theme selection. Do not add React or a server runtime.

## Pages and content

- `/` remains the English-default research-results page, with the existing five studies, charts, daily-observation limitations, filters, and source links.
- `/tool.html` remains the tool introduction and beginner setup page.
- Each of the six English research notes gets a first-party page under `/research/<slug>/`; its Chinese reference is available at `/zh-CN/research/<slug>/`. A language switch on a note goes to the matching translation.
- The existing Markdown notes under `docs/research/` and `docs/zh-CN/research/` remain the authoritative text. Astro reads them as content rather than keeping a second copy. Add only the frontmatter needed to identify each note, its language, and its translation pair.
- English remains the default. The language and light/dark theme preferences remain explicit, persistent across pages, and independent of research data.
- The main research page keeps working without its interactive script: Astro renders a summary from the reviewed data, then client-side JavaScript enhances it with charts and filters.

## Data and publishing

The site continues to use the exact reviewed JSON release pinned by `site/research-source.json`. Before Astro builds, the existing Python validation must check the asset's SHA-256, evidence classification, and nested public-field allowlists. The build places validated data and static public assets in the runner's temporary directory, outside the checkout; the final output is static files only.

Do not publish private candidate pools, prompts, raw model responses, credentials, or machine paths. Keep the current research-only, non-point-in-time, non-out-of-sample classification visible. Astro must not fetch live market data or model responses.

## GitHub Pages and paths

The Pages workflow continues to build pull requests without deploying them and deploys only `main`. Configure Astro's site URL and repository base path for `https://runchengxie.github.io/ai-stock-picker/`. All page, asset, note, and language-switch links must work under this base path. Preserve `/` and `/tool.html`; new note pages use the routes listed above.

## Build checks and acceptance

- A production Astro build emits the homepage, `/tool.html`, all twelve language-specific note pages, and their assets under the configured base path.
- A malformed note (missing title, language, date, or translation pair) fails the build. Each English note has exactly one Chinese counterpart with the same stable slug.
- The five study cards and their existing numbers, source fingerprints, classifications, empty daily-series state, and offline rehearsal match the currently pinned research snapshot.
- The language switch and dark-mode preference work across the homepage, tool page, and note pairs. The English default, existing dark-mode behavior, and responsive layout remain available.
- The Pages pull-request build validates content and data without deploying; the `main` workflow deploys the static Astro output.
- Python selection behavior and its evidence contracts do not change.

## Out of scope

No changes to stock-ranking behavior, research results, candidate-generation systems, provider APIs, live price feeds, server-side rendering, accounts, or a React application.
