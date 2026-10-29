/**
 * Search Console import card for the question bank.
 * Google data is read once per authorization; no Google credential is stored.
 */

import { searchdata } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from './toast.js';
import { openModal } from './modal.js';
import { escapeHtml } from '../safe-html.js';

const OUTCOME_KEYS = {
  denied: 'gsc.outcome_denied',
  state_invalid: 'gsc.outcome_state_invalid',
  token_exchange_failed: 'gsc.outcome_failed',
  scope_not_granted: 'gsc.outcome_scope',
  no_property: 'gsc.outcome_no_property',
  permission_denied: 'gsc.outcome_permission',
  rate_limited: 'gsc.outcome_rate_limited',
  upstream_error: 'gsc.outcome_failed',
  not_configured: 'gsc.outcome_failed',
};

function number(value) {
  return Number(value || 0).toLocaleString();
}

function share(value) {
  return value === null || value === undefined ? null : `${Math.round(Number(value) * 100)}%`;
}

export async function loadGscCard(projectId) {
  return searchdata.getGsc(projectId).catch(() => null);
}

export function renderGscCard(summary, { isViewer, readOnlyReason, hasBaseline }) {
  if (!summary || (!summary.configured && summary.status !== 'ready')) return '';
  const disabled = isViewer ? `disabled title="${escapeHtml(readOnlyReason)}"` : '';
  const header = `
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
      <div style="max-width:640px;">
        <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${t('gsc.card_title', {}, 'Real search demand from Google Search Console')}</h3>
        <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('gsc.card_desc', {}, 'Turn the non-branded queries people actually use to find you on Google into AI sampling questions. Read-only access; CiteAura does not keep your Google credentials.')}</p>
      </div>
      ${summary.configured ? `<button type="button" id="btn-gsc-connect" class="btn ${summary.status === 'ready' ? 'btn-secondary' : 'btn-primary'} btn-sm" ${disabled}>${summary.status === 'ready' ? t('gsc.refresh_btn', {}, 'Refresh from Search Console') : t('gsc.connect_btn', {}, 'Connect Search Console')}</button>` : ''}
    </div>`;
  if (summary.status !== 'ready') {
    return `<div class="card" id="gsc-card" style="gap:var(--sp-3);margin-bottom:var(--sp-4);">${header}</div>`;
  }
  const gap = share(summary.anonymous_click_share);
  const items = summary.candidates || [];
  const meta = `
    <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;align-items:center;color:var(--muted);font-size:var(--fs-1);">
      <span class="tag tag-neutral">${escapeHtml(summary.source_label || 'GSC·第一方')}</span>
      <code class="num" style="font-family:inherit;">${escapeHtml(summary.property)}</code>
      <span>·</span>
      <span class="num">${escapeHtml(summary.window.start)} → ${escapeHtml(summary.window.end)}</span>
      <span>·</span>
      <span>${t('gsc.fetched_at', { time: new Date(summary.fetched_at).toLocaleString() }, `Fetched ${new Date(summary.fetched_at).toLocaleString()}`)}</span>
    </div>
    ${gap ? `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('gsc.anonymous_gap', { share: gap }, `Google hides the queries behind ${gap} of clicks; this list covers the visible part only.`)}</p>` : ''}
    ${hasBaseline ? `<div class="read-only-note" role="status">${t('gsc.new_cohort_warning', {}, 'This project already has a sampling baseline. Adding questions starts a new comparable period; earlier results stay attributed to the previous question set.')}</div>` : ''}`;
  const empty = !items.length
    ? `<div style="padding:var(--sp-4);background:var(--page);color:var(--muted);font-size:var(--fs-2);">${t('gsc.empty', {}, 'No non-branded queries with enough Google impressions in the last 90 days. Use Prompt Research above to add questions instead.')}</div>`
    : '';
  const lowVolume = items.length && summary.low_volume
    ? `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('gsc.low_volume', { count: items.length }, `Only ${items.length} usable queries in the last 90 days. Supplement them with Prompt Research.`)}</p>`
    : '';
  const table = items.length ? `
    <div class="tbl" style="overflow-x:auto;">
      <table class="table">
        <thead><tr>
          <th style="width:32px;"><span class="sr-only">${t('gsc.col_select', {}, 'Select')}</span></th>
          <th>${t('gsc.col_prompt', {}, 'Question to sample (editable)')}</th>
          <th>${t('gsc.col_query', {}, 'Google query')}</th>
          <th style="text-align:right;">${t('gsc.col_impressions', {}, 'Impressions')}</th>
          <th style="text-align:right;">${t('gsc.col_clicks', {}, 'Clicks')}</th>
          <th style="text-align:right;">${t('gsc.col_position', {}, 'Avg. position')}</th>
        </tr></thead>
        <tbody>${items.map((item, index) => `
          <tr>
            <td>${item.in_question_bank
              ? `<span class="tag pill-good">${t('questions.in_bank', {}, 'In bank')}</span>`
              : `<input type="checkbox" id="gsc-pick-${index}" data-gsc-pick="${escapeHtml(item.id)}" ${isViewer ? 'disabled' : 'checked'} aria-label="${escapeHtml(item.query)}">`}</td>
            <td style="min-width:280px;">${item.in_question_bank
              ? `<strong><code style="font-family:inherit;">${escapeHtml(item.prompt)}</code></strong>`
              : `<input type="text" id="gsc-text-${index}" class="input" data-gsc-text="${escapeHtml(item.id)}" value="${escapeHtml(item.prompt)}" maxlength="1000" ${isViewer ? 'readonly' : ''}>`}</td>
            <td><code class="tag tag-dim" style="font-family:inherit;">${escapeHtml(item.query)}</code></td>
            <td data-num>${number(item.impressions)}</td>
            <td data-num>${number(item.clicks)}</td>
            <td data-num>${Number(item.position || 0).toFixed(1)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div style="display:flex;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;align-items:center;">
      <button type="button" id="btn-gsc-delete" class="btn btn-ghost btn-sm" ${disabled}>${t('gsc.delete_btn', {}, 'Delete Search Console data')}</button>
      <button type="button" id="btn-gsc-add" class="btn btn-primary btn-sm" ${disabled}>${t('gsc.add_btn', {}, 'Add selected to question bank')}</button>
    </div>` : `<div><button type="button" id="btn-gsc-delete" class="btn btn-ghost btn-sm" ${disabled}>${t('gsc.delete_btn', {}, 'Delete Search Console data')}</button></div>`;
  return `<div class="card" id="gsc-card" style="gap:var(--sp-3);margin-bottom:var(--sp-4);">${header}${meta}${lowVolume}${empty}${table}</div>`;
}

async function startAuthorization(projectId) {
  try {
    const { authorization_url: url } = await searchdata.authorizeGsc(projectId);
    if (url) window.location.assign(url);
  } catch (err) {
    toast.error(tError(err));
  }
}

async function chooseProperty(ctx, projectId, sessionId) {
  let offered;
  try {
    offered = await searchdata.getGscSession(projectId, sessionId);
  } catch (err) {
    toast.error(t('gsc.session_expired', {}, 'The Search Console authorization expired. Connect again.'));
    return;
  }
  const options = (offered.properties || []).map((site, index) => `
    <label style="display:flex;gap:var(--sp-2);align-items:center;">
      <input type="radio" data-gsc-property id="gsc-property-${index}" value="${escapeHtml(site)}" ${index === 0 ? 'checked' : ''}>
      <span class="num">${escapeHtml(site)}</span>
    </label>`).join('');
  openModal({
    title: t('gsc.choose_title', {}, 'Choose a Search Console property'),
    content: `<div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('gsc.choose_desc', { url: offered.project_url }, `This Google account can see several properties. Pick the one for ${offered.project_url}.`)}</p>
      ${options}
    </div>`,
    confirmText: t('gsc.choose_confirm', {}, 'Read queries'),
    onConfirm: async () => {
      const site = document.querySelector('input[data-gsc-property]:checked')?.value;
      if (!site) return false;
      try {
        await searchdata.selectGscProperty(projectId, { session_id: sessionId, site_url: site });
        toast.success(t('gsc.ready', {}, 'Search Console queries loaded'));
        await ctx.reloadCurrentView();
        return true;
      } catch (err) {
        toast.error(tError(err));
        return false;
      }
    },
  });
  // 安全 HTML 会去掉 input 的 name 属性，单选互斥需要手动维护。
  const radios = Array.from(document.querySelectorAll('input[data-gsc-property]'));
  radios.forEach((radio) => radio.addEventListener('change', () => {
    radios.forEach((other) => { other.checked = other === radio; });
  }));
}

/** Handle the redirect back from Google. Returns true when the view must re-render. */
export function handleGscReturn(ctx) {
  const outcome = ctx.params?.gsc;
  if (!outcome) return false;
  const projectParam = ctx.params?.project;
  if (projectParam && String(projectParam) !== String(ctx.activeProjectId)) {
    ctx.setActiveProject(projectParam);
  }
  if (outcome === 'choose' && ctx.params?.gsc_session) {
    const sessionId = ctx.params.gsc_session;
    history.replaceState(null, '', `${location.pathname}#/questions`);
    chooseProperty(ctx, ctx.params.project || ctx.activeProjectId, sessionId);
    return false;
  }
  if (outcome === 'ready') toast.success(t('gsc.ready', {}, 'Search Console queries loaded'));
  else toast.error(t(OUTCOME_KEYS[outcome] || 'gsc.outcome_failed', {}, 'Search Console connection failed. Try again.'));
  ctx.navigate('#/questions');
  return true;
}

export function bindGscCard(ctx, projectId) {
  document.getElementById('btn-gsc-connect')?.addEventListener('click', () => startAuthorization(projectId));
  document.getElementById('btn-gsc-delete')?.addEventListener('click', () => {
    openModal({
      title: t('gsc.delete_title', {}, 'Delete Search Console data?'),
      content: `<p style="margin:0;">${t('gsc.delete_desc', {}, 'This removes the stored query snapshot for this project. Questions already added to the bank stay, including their recorded Google figures.')}</p>`,
      confirmText: t('gsc.delete_btn', {}, 'Delete Search Console data'),
      onConfirm: async () => {
        try {
          await searchdata.deleteGsc(projectId);
          toast.success(t('gsc.deleted', {}, 'Search Console data deleted'));
          await ctx.reloadCurrentView();
          return true;
        } catch (err) {
          toast.error(tError(err));
          return false;
        }
      },
    });
  });
  document.getElementById('btn-gsc-add')?.addEventListener('click', async () => {
    const items = Array.from(document.querySelectorAll('input[data-gsc-pick]:checked')).map((input) => {
      const id = input.getAttribute('data-gsc-pick');
      const text = document.querySelector(`input[data-gsc-text="${CSS.escape(id)}"]`)?.value.trim();
      return { id, text };
    }).filter((item) => item.text);
    if (!items.length) {
      toast.info(t('gsc.nothing_selected', {}, 'Select at least one query'));
      return;
    }
    try {
      const result = await searchdata.addGscQuestions(projectId, { items });
      toast.success(t('gsc.added', { count: result.added }, `${result.added} questions added to the bank`));
      await ctx.reloadCurrentView();
    } catch (err) {
      toast.error(tError(err));
    }
  });
}
