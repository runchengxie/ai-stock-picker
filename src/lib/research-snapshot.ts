import { readFileSync } from 'node:fs';
import { env } from 'node:process';

export type ResearchSnapshot = {
  reviewed_on: string;
  research_only: true;
  strict_point_in_time: false;
  eligible_as_oos_evidence: false;
  sources: Array<{ id: string; file: string; sha256: string }>;
  studies: Record<string, Record<string, any>>;
  daily: { rows: unknown[]; offline_rehearsal: Record<string, any> | null };
};

export function loadResearchSnapshot(): ResearchSnapshot {
  const path = env.AIPICK_RESEARCH_SNAPSHOT;
  if (!path) throw new Error('AIPICK_RESEARCH_SNAPSHOT must point to the validated public snapshot');
  const snapshot = JSON.parse(readFileSync(path, 'utf8')) as ResearchSnapshot;
  if (snapshot.research_only !== true || snapshot.strict_point_in_time !== false || snapshot.eligible_as_oos_evidence !== false) {
    throw new Error('Research snapshot evidence classification is invalid');
  }
  return snapshot;
}

const escapeHtml = (value: unknown) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);

export function renderResearchFallback(snapshot: ResearchSnapshot): string {
  const studies = snapshot.studies;
  const stability = studies.stability;
  const models = studies.models;
  const labels: Array<[string, string]> = [
    ['Model stability checks passed', `${stability.passed} / ${stability.calls}`],
    ['Explanation checks: Flash / Pro', `${models.models.flash.publication_passes} / ${models.models.flash.calls} · ${models.models.pro.publication_passes} / ${models.models.pro.calls}`],
    ['First rule adjustment · one session', `${(studies.guarded.returns.H1.numeric * 100).toFixed(2)}% original · ${(studies.guarded.returns.H1.guarded * 100).toFixed(2)}% adjusted`],
    ['Revised numeric rule · three sessions', `${(studies.numeric.primary.NUMERIC.H3.total_return * 100).toFixed(2)}% original · ${(studies.numeric.primary.NUMERIC_V2.H3.total_return * 100).toFixed(2)}% revised`],
    ['Turnover experiment', `${(studies.turnover.rows.true_3d_b15_e8_margin001_maxnew2_carry.target_name_turnover_per_rebalance * 100).toFixed(0)}% turnover · ${(studies.turnover.rows.true_3d_b15_e8_margin001_maxnew2_carry.mean_stale_candidate_fraction * 100).toFixed(2)}% held stocks outside current pool`],
  ];
  const rehearsal = snapshot.daily.offline_rehearsal;
  const rehearsalSummary = rehearsal
    ? `Offline rehearsal on ${escapeHtml(rehearsal.date)} for the ${escapeHtml(rehearsal.signal_date)} signal: ${escapeHtml(rehearsal.model_calls)} model calls. The bounded choice did not change; the veto matched the simple rule. This was not live performance.`
    : 'No offline rehearsal is included in this snapshot.';
  const sources = snapshot.sources
    .map((source) => `<li><code>${escapeHtml(source.file)}</code> · SHA-256 <code>${escapeHtml(source.sha256)}</code></li>`)
    .join('');
  return `<table><caption>Reviewed research results · reviewed ${escapeHtml(snapshot.reviewed_on)}</caption><tbody>${labels.map(([label, value]) => `<tr><th scope="row">${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`).join('')}</tbody></table><p>${snapshot.daily.rows.length ? `${snapshot.daily.rows.length} reviewed daily observations` : 'No verified continuous daily series is included.'}</p><p>${rehearsalSummary}</p><p>Historical research only. This is not strict point-in-time or qualified out-of-sample evidence.</p><details><summary>Source files and SHA-256 fingerprints</summary><ul>${sources}</ul></details>`;
}
