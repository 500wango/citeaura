import { projects } from '../api.js?v=3.4';
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
  return `Before ${first.cur ?? '—'} → now ${current.cur ?? '—'}${current.target !== undefined ? ` / target ${current.target}` : ''}`;
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: 'No Brand Selected' })}</div>`;
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
            <h1 class="view-title">Verification History</h1>
            <p class="view-desc">Verification re-crawls the site and evaluates ticket acceptance checks against the latest audit and metrics artifacts.</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-run-verify-now" class="btn btn-primary btn-sm" ${canVerify ? '' : 'disabled'}>
              Run Verification
            </button>
          </div>
        </div>
        ${!canVerify ? renderEmpty({ title: 'No action tickets yet', description: 'Generate or create tickets before running verification.' }) : ''}
        ${history.length ? `
          <div class="card" style="padding:0;overflow:hidden;margin-bottom:var(--sp-4);">
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>Verified at</th><th style="text-align:right;">Closed</th><th style="text-align:right;">Reopened</th><th style="text-align:right;">Pass / Fail / Manual</th></tr></thead>
                <tbody>${history.map((item) => {
                  const summary = summarize(item);
                  return `<tr><td><strong class="num">${escapeHtml(item.verified_at || 'Unknown')}</strong></td><td data-num>${summary.closed}</td><td data-num>${summary.reopened}</td><td data-num>${summary.passCount} / ${summary.failCount} / ${summary.manualCount}</td></tr>`;
                }).join('')}</tbody>
              </table>
            </div>
          </div>
          ${latest?.results?.length ? `
            <div class="card" style="padding:0;overflow:hidden;">
              <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);"><strong>Latest ticket results</strong></div>
              <div class="tbl" style="overflow-x:auto;">
                <table class="table">
                  <thead><tr><th>Ticket</th><th>Verdict</th><th>Before → After</th><th>Evidence</th><th></th></tr></thead>
                  <tbody>
                    ${latest.results.map((item) => `
                      <tr>
                        <td><strong>${escapeHtml(item.title || item.id)}</strong><div class="num">${escapeHtml(item.id || '')}</div></td>
                        <td>${escapeHtml(item.verdict || 'manual')}</td>
                        <td>${escapeHtml(`${item.was || '—'} → ${item.now || '—'}`)}${progressLabel(item) ? `<div class="num">${escapeHtml(progressLabel(item))}</div>` : ''}</td>
                        <td>${escapeHtml(item.note || '')}</td>
                        <td>${item.verdict === 'manual' ? `<button type="button" class="btn btn-secondary btn-sm btn-confirm-manual" data-tid="${escapeHtml(item.id)}">Mark accepted</button>` : ''}</td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>` : ''}
        ` : (canVerify ? renderEmpty({ title: 'No verification runs yet', description: 'Run verification after deploying tickets to record pass, fail, and reopen states.' }) : '')}
      </div>`;
  },
  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    document.getElementById('btn-run-verify-now')?.addEventListener('click', async () => {
      const btn = document.getElementById('btn-run-verify-now');
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      try {
        const res = await projects.triggerVerify(projectId);
        toast.success('Verification queued');
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'verify');
      } catch (err) {
        toast.error(err.detail || 'Failed to start verification');
      } finally {
        btn.disabled = false;
      }
    });
    document.querySelectorAll('.btn-confirm-manual').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          await projects.patchTicket(projectId, button.getAttribute('data-tid'), {
            status: 'done',
            note: 'Manually accepted after verification review',
          });
          toast.success('Ticket marked accepted');
          await ctx.reloadCurrentView();
        } catch (err) {
          toast.error(err.detail || 'Failed to accept ticket');
        }
      });
    });
  },
};
