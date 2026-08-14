import { projects } from '../api.js?v=3.4';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

function summarize(historyItem) {
  const results = historyItem.results || [];
  const closed = results.filter((item) => item.was !== 'done' && item.now === 'done').length;
  const reopened = results.filter((item) => item.was === 'done' && item.now !== 'done').length;
  const passCount = results.filter((item) => item.verdict === 'pass').length;
  const failCount = results.filter((item) => item.verdict === 'fail').length;
  const manualCount = results.filter((item) => item.verdict === 'manual').length;
  return { closed, reopened, passCount, failCount, manualCount };
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: 'No Brand Selected' })}</div>`;
    const history = await projects.getVerifyHistory(projectId).catch(() => []);
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">Verification History</h1>
            <p class="view-desc">Verification re-crawls the site and evaluates ticket acceptance checks against the latest audit and metrics artifacts.</p>
          </div>
          <div class="view-actions"><button type="button" id="btn-run-verify-now" class="btn btn-primary btn-sm">Run Verification</button></div>
        </div>
        ${history.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>Verified at</th><th style="text-align:right;">Closed</th><th style="text-align:right;">Reopened</th><th style="text-align:right;">Pass / Fail / Manual</th></tr></thead>
                <tbody>${history.map((item) => {
                  const summary = summarize(item);
                  return `<tr><td><strong class="num">${item.verified_at || 'Unknown'}</strong></td><td data-num>${summary.closed}</td><td data-num>${summary.reopened}</td><td data-num>${summary.passCount} / ${summary.failCount} / ${summary.manualCount}</td></tr>`;
                }).join('')}</tbody>
              </table>
            </div>
          </div>` : renderEmpty({ title: 'No verification runs yet', description: 'Run verification after deploying tickets to record pass, fail, and reopen states.' })}
      </div>`;
  },
  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    document.getElementById('btn-run-verify-now')?.addEventListener('click', async () => {
      const btn = document.getElementById('btn-run-verify-now');
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
  },
};
