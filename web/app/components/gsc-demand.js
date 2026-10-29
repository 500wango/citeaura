/**
 * "Real search demand" report section: Google figures beside AI sampling results.
 * Kept separate from the GEO health score.
 */

import { analytics, searchdata } from '../api.js';
import { t } from '../i18n.js';
import { samplingModeLabel } from './badge.js';
import { escapeHtml } from '../safe-html.js';

export async function loadGscDemand(projectId) {
  return searchdata.getGscDemand(projectId).catch(() => null);
}

const QUERY_SLOT = '__GSC_QUERY__';

// 查询原文放进 <code>，避免界面级文本本地化把用户的 Google 查询改写。
function queryLabel(query) {
  const label = escapeHtml(t('gsc.from_query', { query: QUERY_SLOT }, `Google query: ${QUERY_SLOT}`));
  return label.replace(QUERY_SLOT, `<code style="font-family:inherit;">${escapeHtml(query || '')}</code>`);
}

function engineCell(engine) {
  const mark = engine.mentioned
    ? `<span class="tag pill-good">${t('gsc.demand_mentioned', {}, 'Mentioned')}</span>`
    : `<span class="tag pill-bad">${t('gsc.demand_not_mentioned', {}, 'Not mentioned')}</span>`;
  return `<div style="display:flex;flex-direction:column;gap:2px;margin-bottom:var(--sp-2);">
    <div style="display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap;">
      <strong style="font-size:var(--fs-2);">${escapeHtml(engine.engine_name || engine.engine_code)}</strong>${mark}
    </div>
    <span style="color:var(--muted);font-size:var(--fs-1);">${escapeHtml(samplingModeLabel(engine.sampling_mode_code || engine.sampling_mode))} · n=${Number(engine.samples || 0)}${engine.model_id ? ` · ${escapeHtml(engine.model_id)}` : ''}</span>
    ${engine.competitors?.length ? `<span style="color:var(--muted);font-size:var(--fs-1);">${t('gsc.demand_competitors', {}, 'Recommended instead:')} ${escapeHtml(engine.competitors.join(', '))}</span>` : ''}
  </div>`;
}

export function renderGscDemand(demand) {
  if (!demand || demand.status === 'no_gsc_questions' || !demand.items?.length) return '';
  analytics.track('gsc_report_viewed', { status: demand.status });
  const summary = demand.summary || {};
  const snapshot = demand.snapshot;
  const headline = demand.status === 'measured'
    ? t('gsc.demand_headline', { mentioned: summary.mentioned, measured: summary.measured }, `AI answers mention you in ${summary.mentioned} of ${summary.measured} questions people search for on Google.`)
    : t('gsc.demand_awaiting', { count: summary.questions }, `${summary.questions} Google search questions are in the bank. Run a sample to see whether AI answers mention you.`);
  const gap = snapshot && snapshot.anonymous_click_share != null ? `${Math.round(snapshot.anonymous_click_share * 100)}%` : null;
  return `
    <section class="card" style="gap:var(--sp-3);">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
        <div style="max-width:720px;">
          <span class="kicker">${t('gsc.demand_kicker', {}, 'Real search demand')}</span>
          <h3 style="font-size:var(--fs-4);font-weight:600;margin:4px 0 0;">${escapeHtml(headline)}</h3>
        </div>
        ${demand.status === 'measured' ? '' : '<a href="#/engines" class="btn btn-primary btn-sm">' + t('gsc.demand_run_sample', {}, 'Run a sample') + '</a>'}
      </div>
      <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('gsc.demand_note', {}, 'Google figures come from your Search Console (first-party, last 90 days). AI results come from labeled sampling. Neither feeds the GEO health score, and a match here does not prove the AI answer drives the Google traffic.')}</p>
      ${snapshot ? `<div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;color:var(--muted);font-size:var(--fs-1);">
        <span class="tag tag-neutral">GSC·第一方</span>
        <code class="num" style="font-family:inherit;">${escapeHtml(snapshot.property)}</code><span>·</span>
        <span class="num">${escapeHtml(snapshot.window.start)} → ${escapeHtml(snapshot.window.end)}</span>
        ${gap ? `<span>·</span><span>${t('gsc.anonymous_gap_short', { share: gap }, `${gap} of clicks have hidden queries`)}</span>` : ''}
      </div>` : ''}
      <div class="tbl" style="overflow-x:auto;">
        <table class="table">
          <thead><tr>
            <th>${t('gsc.col_prompt_sampled', {}, 'Question sampled')}</th>
            <th style="text-align:right;">${t('gsc.col_impressions', {}, 'Impressions')}</th>
            <th style="text-align:right;">${t('gsc.col_clicks', {}, 'Clicks')}</th>
            <th style="text-align:right;">${t('gsc.col_position', {}, 'Avg. position')}</th>
            <th>${t('gsc.col_ai_result', {}, 'AI answers')}</th>
          </tr></thead>
          <tbody>${demand.items.map((item) => `
            <tr>
              <td style="min-width:260px;"><strong><code style="font-family:inherit;">${escapeHtml(item.text || '')}</code></strong>
                <div style="color:var(--muted);font-size:var(--fs-1);margin-top:3px;">${queryLabel(item.google.query)}</div></td>
              <td data-num>${Number(item.google.impressions || 0).toLocaleString()}</td>
              <td data-num>${Number(item.google.clicks || 0).toLocaleString()}</td>
              <td data-num>${Number(item.google.position || 0).toFixed(1)}</td>
              <td style="min-width:240px;">${item.measured ? item.engines.map(engineCell).join('') : `<span class="tag tag-dim">${t('common.unmeasured', {}, 'Unmeasured')}</span>`}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </section>`;
}
