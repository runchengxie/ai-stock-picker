# Astro Research Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the research dashboard, tool introduction, and bilingual experiment notes into an Astro site deployed at the current GitHub Pages URL.

**Architecture:** Astro prerenders the homepage, `/tool.html`, and note pages from Markdown content collections. The existing Python snapshot validator remains the gate for the pinned public research JSON; Actions stages its validated output in the runner temp directory and passes it to Astro for rendering and publication. Small browser scripts retain charts, filters, language choice, and theme choice.

**Tech Stack:** Astro 7.3.5, Node.js 24, npm with committed `package-lock.json`, TypeScript/Zod content schemas, existing Python standard-library snapshot validator, GitHub Pages Actions.

**Spec:** `docs/superpowers/specs/2026-10-01-astro-research-site-design.md`

## Global Constraints

- Keep `https://runchengxie.github.io/ai-stock-picker/`, `/`, and `/tool.html` working.
- English is the default; provide paired Chinese note routes and preserve language and theme preferences across pages.
- Build static files only; do not add React, a server runtime, market-data requests, or model calls.
- Validate the exact pinned research snapshot and its SHA-256, evidence classification, and nested public-field allowlists before publication.
- Keep generated snapshots and build output outside the repository checkout.
- Do not publish private candidate pools, prompts, raw model responses, credentials, or machine paths.
- Preserve all five study results, source fingerprints, daily-observation limits, and the explicit research-only classification.
- Do not change the Python selection behavior or evidence contracts.
- Node.js 24 is the build/runtime floor for the website; Astro 7 requires Node.js 22.12 or newer.

## Review Focus

- Missing snapshot or changed digest: the publish build fails before creating output; test in Task 1.
- Unexpected private fields nested in study or rehearsal data: the public allowlist rejects them; test in Task 1.
- Missing, duplicate, or mismatched English/Chinese notes: content validation fails the build; test in Task 2.
- Repository base path omitted from a generated link or asset: production output still uses `/ai-stock-picker/`; test in Task 3.
- JavaScript unavailable or blocked: rendered research summary and individual notes remain readable; test in Task 3.

---

## File map

- `package.json`, `package-lock.json`, `astro.config.mjs`, `tsconfig.json`: pinned Astro toolchain, GitHub Pages URL/base, and build commands.
- `src/content.config.ts`: typed loaders and schema for the existing English and Chinese Markdown research notes.
- `src/layouts/SiteLayout.astro`, `src/components/LanguageSwitch.astro`, `src/components/ThemeSwitch.astro`: shared page shell and accessible persistent controls.
- `src/pages/index.astro`, `src/pages/tool.html.astro`, `src/pages/research/[slug].astro`, `src/pages/zh-CN/research/[slug].astro`: preserved entry routes and generated bilingual note routes.
- `src/scripts/research.js`, `src/scripts/theme.js`, `src/styles/site.css`: browser-only dashboard behavior, early theme selection, and shared light/dark styling.
- `scripts/site/build.py`, `tests/site/test_build.py`: retain snapshot validation and stage only the validated JSON outside the checkout.
- `.github/workflows/pages.yml`: install the locked Node toolchain, validate/stage the data, build Astro to runner temp, and deploy only from `main`.
- `docs/research/*.md`, `docs/zh-CN/research/*.md`: remain the authoritative English notes and Chinese translations, with only the metadata Astro needs added.
- `docs/showcase.md`, `docs/zh-CN/showcase.md`, `docs/README.md`, `docs/zh-CN/README.md`, `README.md`, `docs/zh-CN/README-project.md`: update local preview and note links to the new Astro routes.

### Task 1: Add the Astro build foundation and preserve snapshot validation

**Files:**
- Create: `package.json`, `package-lock.json`, `astro.config.mjs`, `tsconfig.json`, `src/env.d.ts`
- Create: `scripts/site/stage_snapshot.py`
- Modify: `scripts/site/build.py`, `tests/site/test_build.py`, `.github/workflows/pages.yml`
- Test: `tests/site/test_stage_snapshot.py`

**Interfaces:**
- Produces `stage_snapshot(snapshot: Path, expected_sha256: str, output: Path) -> Path`; it validates through `read_snapshot`, refuses output inside the checkout or over an existing file, and returns the staged JSON path.
- Astro uses `site: 'https://runchengxie.github.io'` and `base: '/ai-stock-picker'`.
- `npm run build -- --outDir <runner-temp-output>` creates static output; build-time research rendering reads the staged path from `AIPICK_RESEARCH_SNAPSHOT`.

- [ ] **Step 1: Add `test_stage_snapshot.py` cases** for valid pinned output, digest mismatch, nested private-field injection, output inside the checkout, and existing output preservation.
- [ ] **Step 2: Run** `uv run pytest tests/site/test_stage_snapshot.py --no-cov -q`; confirm the new interface is missing or the assertions fail.
- [ ] **Step 3: Implement** the staging interface by reusing `read_snapshot`; do not duplicate or weaken the current validator. Add Astro 7 and Node 24 scripts (`dev`, `check`, `build`, `preview`) and commit the npm lockfile.
- [ ] **Step 4: Run** `uv run pytest tests/site/test_stage_snapshot.py tests/site/test_build.py --no-cov -q`, `npm ci --no-audit`, `npm run check`, and `npm audit`; confirm the staging tests and Astro project check pass, the committed lockfile installs cleanly, and the dependency audit reports zero vulnerabilities.
- [ ] **Step 5: Update the Pages workflow** to use `actions/setup-node@v4` with Node 24 and `npm ci`, validate the downloaded release into `$RUNNER_TEMP`, and send Astro output to `$RUNNER_TEMP`.
- [ ] **Step 6: Commit** the build foundation and snapshot-staging changes.

### Task 2: Load and validate bilingual Markdown note pairs

**Files:**
- Create: `src/content.config.ts`, `src/lib/research-notes.ts`, `tests/site/research-notes.test.mjs`
- Modify: all six `docs/research/*.md` notes and matching `docs/zh-CN/research/*.md` notes

**Interfaces:**
- Export `listResearchNotes(entries: CollectionEntry<'research'>[]): ResearchNote[]`; it validates unique stable slugs, supported language values `en` and `zh-CN`, required title/date/summary metadata, and exactly one English and one Chinese entry per slug.
- The Astro `research` collection loads the two existing Markdown trees with Astro's `glob()` loader; those files remain the only copies of the note text.

- [ ] **Step 1: Add unit cases** for a complete pair, missing translation, duplicate locale for a slug, invalid language, and missing metadata.
- [ ] **Step 2: Run** `node --test tests/site/research-notes.test.mjs`; confirm missing validation fails as expected.
- [ ] **Step 3: Add frontmatter** to each note with `title`, `summary`, `date`, `language`, and `slug`; define the Astro Zod schema and implement `listResearchNotes`.
- [ ] **Step 4: Run** `node --test tests/site/research-notes.test.mjs` and `npm run check`; confirm all pairs validate and missing/malformed cases fail.
- [ ] **Step 5: Commit** the content schema and note metadata.

### Task 3: Render the homepage, tool page, and bilingual note routes

**Files:**
- Create: `src/layouts/SiteLayout.astro`, `src/components/ResearchDashboard.astro`, `src/components/LanguageSwitch.astro`, `src/components/ThemeSwitch.astro`, `src/pages/index.astro`, `src/pages/tool.html.astro`, `src/pages/research/[slug].astro`, `src/pages/zh-CN/research/[slug].astro`, `tests/site/astro-output.test.mjs`
- Create or move into Astro: `src/scripts/research.js`, `src/scripts/theme.js`, `src/styles/site.css`
- Modify: `site/research-model.mjs`, `tests/site/research-model.test.mjs`, `scripts/site/build.py`

**Interfaces:**
- `SiteLayout` owns canonical metadata, base-prefixed assets, shared navigation, locale, and theme controls.
- `ResearchDashboard` receives the already validated snapshot as a typed `ResearchSnapshot` and renders its complete static summary before client scripts enhance it.
- Note routes use the paired collection entries from Task 2 and generate all six slugs in both languages.

- [ ] **Step 1: Add build-output assertions** for `/index.html`, `/tool.html`, twelve note pages, base-prefixed CSS/JS links, rendered note links, the fallback summary, and research-only classification.
- [ ] **Step 2: Run** `npm run build` with a validated staged snapshot; confirm the new routes and assertions fail before implementation.
- [ ] **Step 3: Implement** the shared Astro layout and page components. Move the existing dashboard and theme behavior into Astro-managed scripts; derive every internal asset and route URL from `import.meta.env.BASE_URL`.
- [ ] **Step 4: Render** all result counts, charts' accessible text, study limitations, daily empty state, offline rehearsal, and source fingerprints from the validated snapshot; keep existing metric helpers and tests.
- [ ] **Step 5: Add the paired note pages** and make language switching navigate to the equivalent note. Keep persisted locale/theme keys `aipick.locale` and `aipick.theme`.
- [ ] **Step 6: Run** `npm run check`, `node --test tests/site/*.test.mjs`, and `npm run build` with the staged snapshot; inspect the built HTML assertions and the route list.
- [ ] **Step 7: Commit** the Astro pages and client enhancements.

### Task 4: Switch Pages to Astro and update reader/developer links

**Files:**
- Modify: `.github/workflows/pages.yml`, `docs/showcase.md`, `docs/zh-CN/showcase.md`, `docs/README.md`, `docs/zh-CN/README.md`, `README.md`, `docs/zh-CN/README-project.md`
- Remove after route parity is established: old `site/index.html`, `site/tool.html`, `site/app.js`, `site/tool.js`, `site/styles.css`, `site/research.css`, `site/theme.js` and their obsolete localization files

**Interfaces:**
- The Pages build receives `AIPICK_RESEARCH_SNAPSHOT` from the staged validated asset; only the build job may stage it.
- The deploy job remains restricted to successful `main` builds and uploads only the Astro `dist` output.

- [ ] **Step 1: Add workflow checks** that verify the release checksum, run `npm ci`, `npm run check`, Node metric/content tests, and build to `$RUNNER_TEMP` with the staged snapshot.
- [ ] **Step 2: Run the workflow-equivalent commands locally** and inspect that no generated data or build output appears in the checkout.
- [ ] **Step 3: Update** README and showcase documentation with Node 24/Astro commands, public note routes, preview instructions, and the existing GitHub Pages URL; keep Python tool installation separate.
- [ ] **Step 4: Remove the old static-page source** after the Astro output tests prove the two previous routes and all content have replacements; remove obsolete locale entries without dropping tool-page translations.
- [ ] **Step 5: Run** `uv run python scripts/dev/check.py`, `npm run check`, `node --test tests/site/*.test.mjs`, and the full Astro output build.
- [ ] **Step 6: Commit** the deployment and documentation cutover.
