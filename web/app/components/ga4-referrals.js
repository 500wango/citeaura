/**
 * Report section: first-party AI referral traffic from Google Analytics 4.
 */

import { searchdata } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';

function number(value) {
  return Number(value || 0).toLocaleString();
}

function percent(value) {
  if (value === null || value === undefined) return '—';
  const pct = Number(value) * 100;
  return `${pct >= 1 ? pct.toFixed(1) : pct.toFixed(2)}%`;
}

export async function loadGa4(projectId) {
  return searchdata.getGa4(projectId).catch(() => null);
}

export function renderGa4Referrals(summary) {
  if (!summary) return '';
  const days = summary.window?.days || 28;
  if (summary.status !== 'ready') {
    if (!summary.configured) return '';
    return `<section class="card" style="gap:var(--sp-3);">
      <div class="kicker">${t('ga4.report_kicker', {}, 'AI referral traffic')}</div>
      <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_connect_desc', {}, 'Connect a GA4 property to see how many sessions AI assistants send to your site.')}</p>
      <a href="#/project-settings" class="btn btn-secondary btn-sm" style="align-self:flex-start;">${t('ga4.report_connect_cta', {}, 'Connect Google Analytics 4')}</a>
    </section>`;
  }
  const totals = summary.ai_totals || {};
  const site = summary.site_totals || {};
  const keyEvents = summary.key_events || {};
  const engines = summary.engines || [];
  const coverage = summary.coverage || {};
  const keyEventsNote = keyEvents.status === 'ok'
    ? t('ga4.report_key_events_ok', { count: keyEvents.count }, `${keyEvents.count} key events are configured for this property.`)
    : keyEvents.status === 'not_configured'
      ? t('ga4.report_key_events_none', {}, 'This property has no key events configured; key event counts will be 0.')
      : t('ga4.report_key_events_unavailable', {}, 'Key event configuration could not be read from Google.');
  const headline = summary.no_ai_traffic
    ? t('ga4.report_no_ai', { days }, `No recognized AI referral sessions in the last ${days} days.`)
    : !site.sessions
      ? t('ga4.report_no_site_sessions', { days }, `No site sessions recorded in the last ${days} days, so a share cannot be calculated.`)
      : t('ga4.report_headline', {
        sessions: number(totals.sessions), share: percent(totals.share_of_sessions), days,
      }, `AI assistants sent ${number(totals.sessions)} sessions (${percent(totals.share_of_sessions)} of all site sessions) in the last ${days} days.`);
  const rows = engines.map((engine) => `
    <tr>
      <td>${escapeHtml(engine.engine_name)}</td>
      <td data-num>${number(engine.sessions)}</td>
      <td data-num>${engine.total_users === null || engine.total_users === undefined ? '—' : number(engine.total_users)}</td>
      <td data-num>${number(engine.key_events)}</td>
      <td data-num>${percent(engine.share_of_sessions)}</td>
      <td><code class="tag tag-dim" style="font-family:inherit;">${escapeHtml((engine.sources || []).join(', '))}</code></td>
    </tr>`).join('');
  const table = engines.length ? `
    <div class="tbl" style="overflow-x:auto;">
      <table class="table">
        <thead><tr>
          <th>${t('ga4.col_engine', {}, 'AI assistant')}</th>
          <th style="text-align:right;">${t('ga4.col_sessions', {}, 'Sessions')}</th>
          <th style="text-align:right;">${t('ga4.col_users', {}, 'Users')}</th>
          <th style="text-align:right;">${t('ga4.col_key_events', {}, 'Key events')}</th>
          <th style="text-align:right;">${t('ga4.col_share', {}, 'Share of site sessions')}</th>
          <th>${t('ga4.col_sources', {}, 'Source domains')}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>` : '';
  const stale = summary.ai_sources_version_stale
    ? `<p style="margin:0;color:var(--warn);font-size:var(--fs-2);">${t('ga4.report_stale_version', { used: summary.ai_sources_version, current: summary.ai_sources_version_current }, `This snapshot used AI domain table ${summary.ai_sources_version}; the current table is ${summary.ai_sources_version_current}. Refresh to update.`)}</p>`
    : '';
  const truncated = coverage.truncated
    ? `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_truncated', {}, 'Only the top sources by sessions were read. Smaller AI sources may be missing.')}</p>`
    : '';
  return `<section class="card" style="gap:var(--sp-3);">
    <div class="kicker">${t('ga4.report_kicker', {}, 'AI referral traffic')}</div>
    <p style="margin:0;font-size:var(--fs-3);">${headline}</p>
    <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;align-items:center;color:var(--muted);font-size:var(--fs-1);">
      <span class="tag tag-neutral">${escapeHtml(summary.source_label || 'GA4·第一方')}</span>
      <span>${escapeHtml(summary.property_display_name || summary.property)}</span>
      <code class="num" style="font-family:inherit;">${escapeHtml(summary.property)}</code>
      <span>·</span>
      <code class="tag tag-dim" style="font-family:inherit;">${escapeHtml(summary.stream_uri || '')}</code>
      <span>·</span>
      <span class="num">${escapeHtml(summary.window.start)} → ${escapeHtml(summary.window.end)}</span>
      <span>·</span>
      <span>${t('ga4.fetched_at', { time: new Date(summary.fetched_at).toLocaleString() }, `Fetched ${new Date(summary.fetched_at).toLocaleString()}`)}</span>
      <span>·</span>
      <span>${t('ga4.table_version', { version: summary.ai_sources_version }, `AI domain table ${summary.ai_sources_version}`)}</span>
    </div>
    <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_site_total', { sessions: number(site.sessions) }, `All site sessions: ${number(site.sessions)}`)} · ${keyEventsNote}</p>
    ${stale}
    ${truncated}
    ${table}
    <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_users_note', {}, 'Users are reported per source; they are not deduplicated across sources.')}</p>
    <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_note', { days }, `First-party GA4 measurement for the last ${days} days. Not part of the GEO health score. AI apps often omit the referrer, so Direct traffic can hide additional AI visits; treat this as a lower bound.`)}</p>
  </section>`;
}
