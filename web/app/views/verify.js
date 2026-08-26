import { projects } from '../api.js?v=3.4';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js?v=1.1';

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
    const [history, tickets] = await Promise.all([
      projects.getVerifyHistory(projectId).catch(() => []),
      projects.getTickets(projectId).catch(() => []),
    ]);
    const latest = history[history.length - 1];
    const canVerify = Array.isArray(tickets) && tickets.length > 0;
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('verify.title', {}, 'Verification History')}</h1>
            <p class="view-desc">${t('verify.desc', {}, 'Verification re-crawls the site and evaluates ticket acceptance checks against the latest audit and metrics artifacts.')}</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-run-verify-now" class="btn btn-primary btn-sm" ${canVerify ? '' : 'disabled'}>
              ${t('verify.run_now', {}, 'Run Verification')}
            </button>
          </div>
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
                  <thead><tr><th>${t('verify.col_ticket', {}, 'Ticket')}</th><th>${t('verify.col_verdict', {}, 'Verdict')}</th><th>${t('verify.col_evidence', {}, 'Evidence')}</th></tr></thead>
                  <tbody>${latest.results.map((item) => `
                    <tr>
                      <td><strong>${escapeHtml(item.ticket_id || 'Ticket')}</strong><div style="font-size:var(--fs-1);color:var(--muted);">${escapeHtml(item.title || '')}</div></td>
                      <td><span class="tag ${item.verdict === 'pass' ? 'pill-good' : item.verdict === 'fail' ? 'pill-bad' : 'tag-dim'}">${escapeHtml(item.verdict || 'pending')}</span></td>
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
    document.getElementById('btn-run-verify-now')?.addEventListener('click', async () => {
      try {
        const res = await projects.triggerAction(ctx.activeProjectId, 'verify');
        toast.success(t('verify.queued_success', {}, 'Verification task queued'));
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'verify');
      } catch (err) {
        toast.error(tError(err, 'verify.queued_failed'));
      }
    });
  },
};
