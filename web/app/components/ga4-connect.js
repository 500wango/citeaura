/**
 * Google Analytics 4 connection card for project settings.
 * Google data is read once per authorization; no Google credential is stored.
 */

import { searchdata } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from './toast.js';
import { openModal } from './modal.js';
import { escapeHtml } from '../safe-html.js';

const OUTCOME_KEYS = {
  denied: 'ga4.outcome_denied',
  state_invalid: 'ga4.outcome_state_invalid',
  token_exchange_failed: 'ga4.outcome_failed',
  scope_not_granted: 'ga4.outcome_scope',
  no_property: 'ga4.outcome_no_property',
  permission_denied: 'ga4.outcome_permission',
  rate_limited: 'ga4.outcome_rate_limited',
  upstream_error: 'ga4.outcome_failed',
  not_configured: 'ga4.outcome_failed',
};

function number(value) {
  return Number(value || 0).toLocaleString();
}

function percent(value) {
  if (value === null || value === undefined) return '—';
  const pct = Number(value) * 100;
  return `${pct >= 1 ? pct.toFixed(1) : pct.toFixed(2)}%`;
}

export async function loadGa4Card(projectId) {
  return searchdata.getGa4(projectId).catch(() => null);
}

export async function startGa4Authorization(projectId) {
  try {
    const { authorization_url: url } = await searchdata.authorizeGa4(projectId);
    if (url) window.location.assign(url);
  } catch (err) {
    toast.error(tError(err));
  }
}

export function renderGa4Card(summary, { isViewer, readOnlyReason }) {
  if (!summary || (!summary.configured && summary.status !== 'ready')) return '';
  const disabled = isViewer ? `disabled title="${escapeHtml(readOnlyReason)}"` : '';
  const ready = summary.status === 'ready';
  const header = `
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
      <div style="max-width:640px;">
        <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${t('ga4.settings_title', {}, 'Google Analytics 4 referral traffic')}</h3>
        <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.settings_desc', { days: 28 }, 'CiteAura reads 28 days of AI referral traffic once per authorization and does not keep your Google credentials.')}</p>
      </div>
      ${summary.configured ? `<button type="button" id="btn-ga4-connect" class="btn ${ready ? 'btn-secondary' : 'btn-primary'} btn-sm" ${disabled}>${ready ? t('ga4.refresh_btn', {}, 'Refresh from Google Analytics') : t('ga4.connect_btn', {}, 'Connect Google Analytics 4')}</button>` : ''}
    </div>`;
  if (!ready) {
    return `<div class="card" id="ga4-card" style="gap:var(--sp-3);">${header}</div>`;
  }
  const totals = summary.ai_totals || {};
  const site = summary.site_totals || {};
  const keyEvents = summary.key_events || {};
  const engines = summary.engines || [];
  const stale = summary.ai_sources_version_stale
    ? `<p style="margin:0;color:var(--warn);font-size:var(--fs-2);">${t('ga4.report_stale_version', { used: summary.ai_sources_version, current: summary.ai_sources_version_current }, `This snapshot used AI domain table ${summary.ai_sources_version}; the current table is ${summary.ai_sources_version_current}. Refresh to update.`)}</p>`
    : '';
  const keyEventsNote = keyEvents.status === 'ok'
    ? t('ga4.report_key_events_ok', { count: keyEvents.count }, `${keyEvents.count} key events are configured for this property.`)
    : keyEvents.status === 'not_configured'
      ? t('ga4.report_key_events_none', {}, 'This property has no key events configured; key event counts will be 0.')
      : t('ga4.report_key_events_unavailable', {}, 'Key event configuration could not be read from Google.');
  const empty = !engines.length
    ? `<div style="padding:var(--sp-4);background:var(--page);color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_no_ai', { days: summary.window?.days || 28 }, `No recognized AI referral sessions in the last ${summary.window?.days || 28} days.`)}</div>`
    : '';
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
  return `<div class="card" id="ga4-card" style="gap:var(--sp-3);">
    ${header}
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
    <div style="display:flex;gap:var(--sp-4);flex-wrap:wrap;font-size:var(--fs-2);">
      <span><strong>${number(totals.sessions)}</strong> ${t('ga4.col_sessions', {}, 'Sessions')}</span>
      <span>${t('ga4.report_headline_share', { share: percent(totals.share_of_sessions) }, `Share of all site sessions: ${percent(totals.share_of_sessions)}`)}</span>
      <span>${t('ga4.report_site_total', { sessions: number(site.sessions) }, `All site sessions: ${number(site.sessions)}`)}</span>
    </div>
    <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${keyEventsNote}</p>
    ${stale}
    ${empty}
    ${table}
    <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.report_note', { days: summary.window?.days || 28 }, 'First-party GA4 measurement. Not part of the GEO health score. AI apps often omit the referrer, so Direct traffic can hide additional AI visits; treat this as a lower bound.')}</p>
    <div>
      <button type="button" id="btn-ga4-delete" class="btn btn-ghost btn-sm" ${disabled}>${t('ga4.delete_btn', {}, 'Delete Google Analytics data')}</button>
    </div>
  </div>`;
}

async function chooseProperty(ctx, projectId, sessionId) {
  let offered;
  try {
    offered = await searchdata.getGa4Session(projectId, sessionId);
  } catch (err) {
    toast.error(t('ga4.session_expired', {}, 'The Google Analytics authorization expired. Connect again.'));
    return;
  }
  const options = (offered.properties || []).map((item, index) => `
    <label style="display:flex;gap:var(--sp-2);align-items:center;">
      <input type="radio" data-ga4-property id="ga4-property-${index}" value="${escapeHtml(item.property)}" ${index === 0 ? 'checked' : ''}>
      <span>${escapeHtml(item.display_name || item.property)}</span>
      <code class="tag tag-dim" style="font-family:inherit;">${escapeHtml(item.stream_uri || item.property)}</code>
    </label>`).join('');
  openModal({
    title: t('ga4.choose_title', {}, 'Choose a Google Analytics property'),
    content: `<div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('ga4.choose_desc', { url: offered.project_url }, `This Google account can see several properties. Pick the one for ${offered.project_url}.`)}</p>
      ${options}
    </div>`,
    confirmText: t('ga4.choose_confirm', {}, 'Read referral traffic'),
    onConfirm: async () => {
      const propertyId = document.querySelector('input[data-ga4-property]:checked')?.value;
      if (!propertyId) return false;
      try {
        await searchdata.selectGa4Property(projectId, { session_id: sessionId, property_id: propertyId });
        toast.success(t('ga4.ready', {}, 'Google Analytics referral traffic loaded'));
        await ctx.reloadCurrentView();
        return true;
      } catch (err) {
        toast.error(tError(err));
        return false;
      }
    },
  });
  // 安全 HTML 会去掉 input 的 name 属性，单选互斥需要手动维护。
  const radios = Array.from(document.querySelectorAll('input[data-ga4-property]'));
  radios.forEach((radio) => radio.addEventListener('change', () => {
    radios.forEach((other) => { other.checked = other === radio; });
  }));
}

/** Handle the redirect back from Google. Returns true when the view must re-render. */
export function handleGa4Return(ctx) {
  const outcome = ctx.params?.ga4;
  if (!outcome) return false;
  const projectParam = ctx.params?.project;
  if (projectParam && String(projectParam) !== String(ctx.activeProjectId)) {
    ctx.setActiveProject(projectParam);
  }
  if (outcome === 'choose' && ctx.params?.ga4_session) {
    const sessionId = ctx.params.ga4_session;
    history.replaceState(null, '', `${location.pathname}#/report`);
    chooseProperty(ctx, projectParam || ctx.activeProjectId, sessionId);
    return false;
  }
  if (outcome === 'ready') toast.success(t('ga4.ready', {}, 'Google Analytics referral traffic loaded'));
  else toast.error(t(OUTCOME_KEYS[outcome] || 'ga4.outcome_failed', {}, 'Google Analytics connection failed. Try again.'));
  ctx.navigate('#/report');
  return true;
}

export function bindGa4Card(ctx, projectId) {
  document.getElementById('btn-ga4-connect')?.addEventListener('click', () => startGa4Authorization(projectId));
  document.getElementById('btn-ga4-delete')?.addEventListener('click', () => {
    openModal({
      title: t('ga4.delete_title', {}, 'Delete Google Analytics data?'),
      content: `<p style="margin:0;">${t('ga4.delete_desc', {}, 'This removes the stored GA4 referral snapshot for this project. Search Console data and questions are not affected.')}</p>`,
      confirmText: t('ga4.delete_btn', {}, 'Delete Google Analytics data'),
      onConfirm: async () => {
        try {
          await searchdata.deleteGa4(projectId);
          toast.success(t('ga4.deleted', {}, 'Google Analytics data deleted'));
          await ctx.reloadCurrentView();
          return true;
        } catch (err) {
          toast.error(tError(err));
          return false;
        }
      },
    });
  });
}
