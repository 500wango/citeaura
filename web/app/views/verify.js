import { analytics, projects } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

function summarize(historyItem) {
  const results = historyItem.results || [];
  const closed = results.filter((item) => item.was !== 'done' && item.now === 'done').length;
  const reopened = results.filter((item) => item.was === 'done' && item.now !== 'done').length;
  const passCount = results.filter((item) => item.verdict === 'pass').length;
  const failCount = results.filter((item) => item.verdict === 'fail').length;
  const manualCount = results.filter((item) => item.verdict === 'manual').length;
  return { closed, reopened, passCount, failCount, manualCount };
}

function progressLabel(item) {
  const current = item.progress || {};
  const first = item.progress_first || {};
  if (current.cur === undefined && first.cur === undefined) return '';
  const targetStr = current.target !== undefined ? t('verify.target_suffix', { target: current.target }, ` / target ${current.target}`) : '';
  return t('verify.progress_format', { before: first.cur ?? '—', now: current.cur ?? '—', target: targetStr }, `Before ${first.cur ?? '—'} → now ${current.cur ?? '—'}${targetStr}`);
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const [history, tickets, jobs] = await Promise.all([
      projects.getVerifyHistory(projectId).catch(() => []),
      projects.getTickets(projectId).catch(() => []),
      projects.getJobs(projectId).catch(() => []),
    ]);
    const latest = history[history.length - 1];
    const activeJob = Array.isArray(jobs) ? jobs.find((job) => ['queued', 'running'].includes(job.status)) : null;
    const isViewer = ctx.role === 'viewer';
    const canVerify = Array.isArray(tickets) && tickets.length > 0 && !activeJob && !isViewer;
    const verifyBlockReason = isViewer
      ? t('plan.viewer_read_only', {}, 'Viewer access: you can inspect evidence but cannot change tickets or plans.')
      : activeJob
        ? t('project_job_already_running', {}, 'A job is already running for this brand.')
        : t('verify.no_tickets_desc', {}, 'Generate or create tickets before running verification.');
    const effectLabels = {
      draft: t('plan.effect_draft', {}, 'Draft'),
      deployed: t('plan.effect_deployed', {}, 'Deployed'),
      observing: t('plan.effect_observing', {}, 'Observing'),
      effective: t('plan.effect_effective', {}, 'Effective'),
      ineffective: t('plan.effect_ineffective', {}, 'Ineffective'),
      inconclusive: t('plan.effect_inconclusive', {}, 'Inconclusive'),
    };
    const effectByTicket = new Map();
    const effectCounts = { effective: 0, ineffective: 0, inconclusive: 0 };
    (tickets || []).forEach((ticket) => {
      const state = String(ticket?.effect?.state || '');
      if (ticket?.id) effectByTicket.set(String(ticket.id), ticket.effect || {});
      if (state in effectCounts) effectCounts[state] += 1;
    });
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('verify.title', {}, 'Verification History')}</h1>
            <p class="view-desc">${t('verify.desc', {}, 'Verification re-crawls the site and evaluates ticket acceptance checks against the latest audit and metrics artifacts.')}</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-run-verify-now" class="btn btn-primary btn-sm" ${canVerify ? '' : `disabled title="${escapeHtml(verifyBlockReason)}"`}>
              ${t('verify.run_now', {}, 'Run Verification')}
            </button>
          </div>
        </div>
        ${isViewer ? `<div class="read-only-note" role="status">${escapeHtml(t('plan.viewer_read_only', {}, 'Viewer access: you can inspect evidence but cannot change tickets or plans.'))}</div>` : ''}
        ${activeJob ? `<div class="job-block-note" role="status"><span class="status-dot"></span>${escapeHtml(t('project_job_already_running', {}, 'A job is already running for this brand.'))} ${escapeHtml(activeJob.action || '')} · ${escapeHtml(activeJob.status || '')}</div>` : ''}
        <div class="card" style="gap:var(--sp-2);border-left:3px solid var(--accent);margin-bottom:var(--sp-4);">
          <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;"><strong>${t('verify.progress_title', {}, 'What verification proves')}</strong><span class="tag tag-dim">${t('verify.technical_only', {}, 'Technical check only')}</span></div>
          <span style="color:var(--ink-2);font-size:var(--fs-2);line-height:1.5;">${t('verify.progress_help', {}, 'A pass means the configured website check succeeded. It does not by itself prove that AI recommendations or traffic increased; those require a comparable measurement cycle.')}</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--sp-2);margin-bottom:var(--sp-4);">
          ${[
            ['effective', t('plan.effect_effective', {}, 'Effective'), 'var(--good)'],
            ['ineffective', t('plan.effect_ineffective', {}, 'Ineffective'), 'var(--bad)'],
            ['inconclusive', t('plan.effect_inconclusive', {}, 'Inconclusive'), 'var(--muted)'],
          ].map(([state, label, color]) => `<div class="card" style="padding:var(--sp-3);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${escapeHtml(label)}</span><strong style="font-size:var(--fs-5);color:${color};">${effectCounts[state]}</strong></div>`).join('')}
        </div>
        ${!canVerify ? renderEmpty({ title: t('verify.no_tickets_title', {}, 'No action tickets yet'), description: t('verify.no_tickets_desc', {}, 'Generate or create tickets before running verification.') }) : ''}
        ${history.length ? `
          <div class="card" style="padding:0;overflow:hidden;margin-bottom:var(--sp-4);">
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>${t('verify.col_verified_at', {}, 'Verified at')}</th><th style="text-align:right;">${t('verify.col_closed', {}, 'Closed')}</th><th style="text-align:right;">${t('verify.col_reopened', {}, 'Reopened')}</th><th style="text-align:right;">${t('verify.col_summary', {}, 'Pass / Fail / Manual')}</th></tr></thead>
                <tbody>${history.map((item) => {
                  const summary = summarize(item);
                  return `<tr><td><strong class="num">${escapeHtml(item.verified_at || 'Unknown')}</strong></td><td data-num>${summary.closed}</td><td data-num>${summary.reopened}</td><td data-num>${summary.passCount} / ${summary.failCount} / ${summary.manualCount}</td></tr>`;
                }).join('')}</tbody>
              </table>
            </div>
          </div>
          ${latest?.results?.length ? `
            <div class="card" style="padding:0;overflow:hidden;">
              <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
                <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('verify.latest_results_title', {}, 'Latest ticket results')}</h3>
              </div>
              <div class="tbl" style="overflow-x:auto;">
                <table class="table">
                  <thead><tr><th>${t('verify.col_ticket', {}, 'Ticket')}</th><th>${t('verify.col_verdict', {}, 'Verdict')}</th><th>${t('verify.col_effect', {}, 'Effect')}</th><th>${t('verify.col_evidence', {}, 'Evidence')}</th></tr></thead>
                  <tbody>${latest.results.map((item) => `
                    <tr>
                      <td><strong>${escapeHtml(item.ticket_id || 'Ticket')}</strong><div style="font-size:var(--fs-1);color:var(--muted);">${escapeHtml(item.title || '')}</div></td>
                      <td><span class="tag ${item.verdict === 'pass' ? 'pill-good' : item.verdict === 'fail' ? 'pill-bad' : 'tag-dim'}">${escapeHtml(item.verdict || 'pending')}</span></td>
                      <td>${(() => { const state = String(effectByTicket.get(String(item.ticket_id))?.state || 'draft'); return `<span class="tag tag-dim">${escapeHtml(effectLabels[state] || state)}</span>`; })()}</td>
                      <td><div>${escapeHtml(item.evidence || '')}</div><div style="font-size:var(--fs-1);color:var(--muted);margin-top:2px;">${escapeHtml(progressLabel(item))}</div></td>
                    </tr>
                  `).join('')}</tbody>
                </table>
              </div>
            </div>` : ''}
        ` : ''}
      </div>`;
  },
  mounted: (ctx) => {
    const verifyNow = document.getElementById('btn-run-verify-now');
    if (!verifyNow || verifyNow.disabled) return;
    verifyNow.addEventListener('click', async () => {
      verifyNow.disabled = true;
      try {
        const res = await projects.triggerAction(ctx.activeProjectId, 'verify');
        toast.success(t('verify.queued_success', {}, 'Verification task queued'));
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'verify');
      } catch (err) {
        toast.error(tError(err, 'verify.queued_failed'));
      } finally {
        verifyNow.disabled = false;
      }
    });
  },
};
