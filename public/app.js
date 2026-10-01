import { passRate, returnRows, sortedDays } from "./research-model.mjs";

const picker = document.getElementById("language");
const app = document.getElementById("research-app");
const filter = document.getElementById("study-filter");
const catalogCache = {};
let english,
  messages,
  data,
  locale = "en",
  version = 0;
const horizons = { guarded: "H1", numeric: "H1" };
const docRoot =
  "https://github.com/runchengxie/ai-stock-picker/blob/main/docs/";
const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const text = (key, values = {}) =>
  (messages?.[key] ?? english?.[key] ?? key).replace(/\{(\w+)\}/g, (_, name) =>
    String(values[name] ?? ""),
  );
const number = (value, digits = 0) =>
  new Intl.NumberFormat(locale, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
const percent = (value) =>
  new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(value);
const dateLabel = (value) =>
  new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T00:00:00Z`));
const plural = (key, count) =>
  text(`${key}.${new Intl.PluralRules(locale).select(count)}`, {
    count: number(count),
  });
const doc = (path) => `${docRoot}${locale === "zh-CN" ? "zh-CN/" : ""}${path}`;

async function loadCatalog(name) {
  if (!catalogCache[name]) {
    const response = await fetch(`./locales/${name}.json`);
    if (!response.ok) throw new Error("Catalog unavailable");
    catalogCache[name] = await response.json();
  }
  return catalogCache[name];
}

function localizePage() {
  document.documentElement.lang = locale;
  document.title = text("research.pageTitle");
  document.querySelector('meta[name="description"]').content = text(
    "research.description",
  );
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = text(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", text(element.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-doc]").forEach((link) => {
    link.href = doc(link.dataset.doc);
  });
  picker.value = locale;
  document.querySelectorAll("[data-note-slug]").forEach((link) => {
    const slug = link.dataset.noteSlug;
    link.href = `${new URL("./", document.querySelector("base").href)}${locale === "zh-CN" ? "zh-CN/" : ""}research/${slug}/`;
    link.textContent = `${locale === "zh-CN" ? link.dataset.noteZh : link.dataset.noteEn} ↗`;
  });
}

function table(headers, rows, caption = "") {
  return `<div class="table-scroll"><table>${caption ? `<caption>${escape(caption)}</caption>` : ""}<thead><tr>${headers.map((value) => `<th scope="col">${escape(value)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((value, index) => `<${index ? "td" : 'th scope="row"'}>${value}</${index ? "td" : "th"}>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function bars(rows, max, signed = false) {
  const contents = rows
    .map(({ key, value, display, color }) => {
      if (typeof value !== "number" || !Number.isFinite(value))
        throw new Error("Missing chart value");
      const width = Math.min(100, Math.max(0, (Math.abs(value) / max) * 100));
      const label = text(key);
      return `<div class="bar-row"><span class="bar-label">${escape(label)}</span><div class="bar-track ${signed && value < 0 ? "negative" : ""}" aria-hidden="true"><div class="bar-fill ${color ?? ""}" style="--width:${width}%"></div></div><span class="bar-value">${escape(display ?? percent(value))}</span></div>`;
    })
    .join("");
  const endpoints = signed
    ? [percent(-max), percent(0)]
    : [number(0), max === 1 ? percent(1) : number(max)];
  return `<div class="chart">${contents}</div><div class="chart-axis" aria-hidden="true"><span>${escape(endpoints[0])}</span><span>${escape(endpoints[1])}</span></div>`;
}

function sources(study) {
  const rows = data.sources
    .filter((source) => study.source_ids.includes(source.id))
    .map((source) => [
      `<span class="source-file">${escape(source.file)}</span>`,
      `<span class="hash">${escape(source.sha256)}</span>`,
    ]);
  return `<details class="study-detail"><summary>${escape(text("research.source"))}</summary><div><p class="method-note">${escape(text("research.source.explainer"))}</p>${table([text("research.source.caption"), text("research.source.hash")], rows)}</div></details>`;
}

function card(id, chart, details = "", state = "research", extra = "") {
  const study = data.studies[id];
  return `<article class="study-card" id="study-${id}"><div class="study-header"><div><h3>${escape(text(`research.${id}.title`))}</h3><p class="study-date">${escape(dateLabel(study.date))}</p></div><span class="study-tag">${escape(text(`research.status.${state}`))}</span></div><p class="question">${escape(text(`research.${id}.question`))}</p><p class="finding">${escape(text(`research.${id}.finding`))}</p>${chart}${extra}${details}${sources(study)}<div class="study-footer"><a class="text-link" href="${doc(`research/${id}.md`)}">${escape(text("research.note"))} ↗</a></div></article>`;
}

function stabilityCard() {
  const s = data.studies.stability;
  const graph = `<p class="chart-title">${escape(text("research.stability.chart"))}</p>${bars(
    Object.entries(s.arms).map(([key, value]) => ({
      key: `research.arm.${key}`,
      value,
      display: text("research.fraction", {
        passed: number(value),
        total: number(s.days),
      }),
    })),
    s.days,
  )}<p class="chart-note">${escape(text("research.stability.denominator"))}</p>`;
  const g = s.gates;
  const interval = (values) =>
    `[${values.map((value) => number(value, 5)).join(", ")}]`;
  const rows = [
    [
      "strict",
      g.strict_success_count,
      `${number(s.passed)} / ${number(s.calls)}`,
      `≥ ${number(s.required)}`,
    ],
    [
      "shuffle",
      g.canonical_shuffle_mean_overlap,
      `${number(g.canonical_shuffle_mean_overlap.observed, 2)} / 10 · ${plural("research.pairs", g.canonical_shuffle_mean_overlap.comparison_count)}`,
      "≥ 8 / 10",
    ],
    [
      "dates",
      g.canonical_shuffle_minimum_overlap_dates,
      number(g.canonical_shuffle_minimum_overlap_dates.observed),
      "≥ 15",
    ],
    [
      "opaque",
      g.canonical_opaque_mean_overlap,
      `${number(g.canonical_opaque_mean_overlap.observed, 2)} / 10 · ${plural("research.pairs", g.canonical_opaque_mean_overlap.comparison_count)}`,
      "≥ 7 / 10",
    ],
    [
      "position",
      g.position_spearman_interval,
      interval(g.position_spearman_interval.observed_ci_95),
      text("research.gate.interval", { interval: "[-0.10, 0.10]" }),
    ],
    [
      "first",
      g.first_row_uplift_interval,
      number(g.first_row_uplift_interval.observed_ci_95[1], 5),
      "≤ 0.10",
    ],
  ].map(([key, gate, observed, required]) => [
    escape(text(`research.gate.${key}`)),
    escape(observed),
    escape(required),
    `<span class="gate-${gate.passed ? "pass" : "fail"}">${escape(text(`research.gate.${gate.passed ? "pass" : "fail"}`))}</span>`,
  ]);
  const details = `<details class="study-detail"><summary>${escape(text("research.stability.gates"))}</summary><div>${table(
    ["name", "observed", "required", "result"].map((key) =>
      text(`research.gate.${key}`),
    ),
    rows,
  )}</div></details>`;
  return card("stability", graph, details, "stopped");
}

function modelsCard() {
  const s = data.studies.models;
  const chart = `<div class="study-grid"><div><p class="chart-title">${escape(text("research.models.chart"))}</p>${bars(
    Object.entries(s.models).map(([key, model]) => ({
      key: key === "pro" ? "research.model.pro" : "research.model.flash",
      value: passRate(model.publication_passes, model.calls),
      display: `${number(model.publication_passes)} / ${number(model.calls)}`,
      color: key === "flash" ? "orange" : "",
    })),
    1,
  )}<p class="chart-note">${escape(text("research.models.threshold", { count: number(s.required), total: number(s.models.flash.calls) }))}</p></div><div>${table(
    [
      text("research.models.model"),
      text("research.models.cost"),
      text("research.models.latency"),
    ],
    Object.entries(s.models).map(([key, model]) => [
      escape(text(`research.model.${key}`)),
      escape(
        new Intl.NumberFormat(locale, {
          style: "currency",
          currency: "CNY",
          maximumFractionDigits: 3,
        }).format(model.estimated_cost_cny),
      ),
      escape(
        text("research.seconds", { value: number(model.latency_seconds, 2) }),
      ),
    ]),
    text("research.models.costTitle"),
  )}<p class="chart-note">${escape(text("research.models.costNote"))}</p></div></div>`;
  return card(
    "models",
    chart,
    "",
    "stopped",
    `<p class="not-run">${escape(text("research.models.notRun"))}</p>`,
  );
}

function horizonControl(id) {
  return `<label class="horizon-control">${escape(text("research.horizon"))}<select data-horizon="${id}">${["H1", "H3", "H5"].map((horizon) => `<option value="${horizon}" ${horizons[id] === horizon ? "selected" : ""}>${escape(text(`research.horizon.${horizon}`))}</option>`).join("")}</select></label>`;
}

function guardedCard() {
  const s = data.studies.guarded,
    values = s.returns[horizons.guarded];
  const graph = `${horizonControl("guarded")}<p class="chart-title">${escape(text("research.returns.title"))}</p>${bars(
    ["numeric", "guarded"].map((key) => ({
      key: `research.series.${key}`,
      value: values[key],
    })),
    1,
    true,
  )}<p class="chart-note">${escape(text("research.returns.note"))}</p><p class="method-note">${escape(text("research.guarded.corrected", { value: number(values.active_corrected_bps, 4) }))}</p><p class="method-note">${escape(text("research.guarded.quality"))}</p>`;
  return card("guarded", graph);
}

function numericCard() {
  const s = data.studies.numeric;
  return card(
    "numeric",
    `${horizonControl("numeric")}<p class="chart-title">${escape(text("research.returns.title"))}</p>${bars(
      returnRows(s, horizons.numeric).map(({ key, value }) => ({
        key: `research.series.${key}`,
        value,
      })),
      1,
      true,
    )}<p class="chart-note">${escape(text("research.returns.note"))}</p><p class="method-note">${escape(text("research.numeric.quality"))}</p>`,
  );
}

function turnoverCard() {
  const s = data.studies.turnover;
  const rows = [
    ["baseline3", s.rows.true_3d_baseline_exit],
    ["cap3", s.rows.true_3d_b15_e8_margin001_maxnew2_carry],
    ["baseline5", s.rows.true_5d_baseline_exit],
    ["cap5", s.rows.true_5d_b15_e8_margin001_maxnew2_carry],
  ];
  const graph = `<div class="study-grid"><div><p class="chart-title">${escape(text("research.turnover.chart"))}</p>${bars(
    rows.map(([key, row]) => ({
      key: `research.turnover.${key}`,
      value: row.target_name_turnover_per_rebalance,
    })),
    1,
  )}</div><div>${table(
    [
      text("research.daily.arm"),
      text("research.turnover.return"),
      text("research.turnover.stale"),
    ],
    rows.map(([key, row]) => [
      escape(text(`research.turnover.${key}`)),
      escape(percent(row.phase_mean_total_return)),
      escape(
        typeof row.mean_stale_candidate_fraction === "number"
          ? percent(row.mean_stale_candidate_fraction)
          : text("research.absent"),
      ),
    ]),
  )}</div></div><p class="chart-note">${escape(text("research.turnover.note"))}</p><p class="method-note">${escape(text("research.turnover.missing"))}</p>`;
  return card("turnover", graph);
}

function renderDaily() {
  const daily = data.daily;
  let content = `<h2>${escape(text("research.daily.title"))}</h2><p class="question">${escape(text("research.daily.explainer"))}</p>`;
  if (!daily.rows.length)
    content += `<p class="empty-state">${escape(text("research.daily.empty"))}</p>`;
  else
    content += table(
      ["date", "model", "arm", "status", "repeats"].map((key) =>
        text(`research.daily.${key}`),
      ),
      sortedDays(daily.rows).map((row) => [
        escape(dateLabel(row.date)),
        escape(row.model),
        escape(text(`research.dailyArm.${row.arm}`)),
        escape(text(`research.status.${row.status}`)),
        escape(`${number(row.valid_repetitions)} / 3`),
      ]),
    );
  const rehearsal = daily.offline_rehearsal;
  if (rehearsal)
    content += `<div class="rehearsal"><span class="study-tag">${escape(text("research.status.offline"))}</span><p>${escape(dateLabel(rehearsal.date))} · ${escape(text("research.daily.date"))}: ${escape(dateLabel(rehearsal.signal_date))}</p><p>${escape(text("research.daily.rehearsal"))}</p>${sources(rehearsal)}</div>`;
  content += `<p class="method-note">${escape(text("research.daily.note"))}</p><a class="text-link" href="${doc("research/daily.md")}">${escape(text("research.daily.read"))} ↗</a>`;
  document.getElementById("daily").innerHTML = content;
}

function render() {
  const studyCount = Object.keys(data.studies).length;
  const calls = data.studies.stability.calls + data.studies.models.calls;
  document.getElementById("topline").innerHTML = [
    [number(studyCount), "studies"],
    [number(calls), "calls"],
    [text("research.stat.no"), "approval"],
  ]
    .map(
      ([value, key]) =>
        `<article><span class="stat-value">${escape(value)}</span><span class="stat-label">${escape(text(`research.stat.${key}`))}</span></article>`,
    )
    .join("");
  document.getElementById("reviewed-date").textContent = text(
    "research.reviewed",
    { date: dateLabel(data.reviewed_on) },
  );
  const selected = filter.value;
  let html = "";
  if (selected !== "rules")
    html += `<h2 class="group-title">${escape(text("research.modelsGroup"))}</h2>${stabilityCard()}${modelsCard()}`;
  if (selected !== "models")
    html += `<h2 class="group-title">${escape(text("research.rulesGroup"))}</h2>${guardedCard()}${numericCard()}${turnoverCard()}`;
  const focusedHorizon = document.activeElement?.dataset?.horizon;
  document.getElementById("results").innerHTML = html;
  if (focusedHorizon)
    document.querySelector(`[data-horizon="${focusedHorizon}"]`)?.focus();
  renderDaily();
}

async function changeLanguage(selected) {
  const current = ++version;
  english = await loadCatalog("en");
  let next = english,
    applied = selected;
  if (selected !== "en") {
    try {
      next = await loadCatalog(selected);
    } catch {
      applied = "en";
    }
  }
  if (current !== version) return;
  messages = next;
  locale = applied;
  localizePage();
  if (data) render();
  try {
    localStorage.setItem("aipick.locale", locale);
  } catch {
    /* Storage is optional. */
  }
}

picker.addEventListener("change", () =>
  changeLanguage(picker.value).catch(() => {
    picker.value = locale;
  }),
);
filter.addEventListener("change", render);
document.getElementById("results").addEventListener("change", (event) => {
  const id = event.target.dataset.horizon;
  if (
    Object.hasOwn(horizons, id) &&
    ["H1", "H3", "H5"].includes(event.target.value)
  ) {
    horizons[id] = event.target.value;
    render();
  }
});

async function start() {
  let initial = "en";
  try {
    if (localStorage.getItem("aipick.locale") === "zh-CN") initial = "zh-CN";
  } catch {
    /* English default. */
  }
  try {
    await changeLanguage(initial);
    picker.disabled = false;
  } catch {
    /* HTML remains usable. */
  }
  const response = await fetch("./data/research.json");
  if (!response.ok) throw new Error("Reviewed data unavailable");
  data = await response.json();
  if (
    data.schema_version !== "research_site.v1" ||
    data.strict_point_in_time !== false ||
    data.eligible_as_oos_evidence !== false ||
    data.research_only !== true
  )
    throw new Error("Invalid evidence classification");
  // Charts require the English fallback catalog even if language loading failed once.
  if (!english) await changeLanguage("en");
  render();
  app.hidden = false;
  document.getElementById("fallback").hidden = true;
  document.getElementById("load-status").hidden = true;
}
start().catch(() => {
  app.hidden = true;
  document.getElementById("fallback").hidden = false;
  data = null;
  document.getElementById("load-status").hidden = true;
  document.getElementById("load-error").hidden = false;
});
