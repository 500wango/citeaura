/**
 *  (Verify & Acceptance Loops)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let history = [];
    try {
      history = await projects.getVerifyHistory(projectId).catch(() => []);
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('verify.title', {}, 'Closed-Loop Verification & Re-crawl')}</h1>
            <p class="view-desc">
              ${t('verify.desc', {}, 'Automatically re-crawl deployed pages, re-sample target questions across AI models, and verify whether implemented tickets resulted in measurable visibility improvements.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-run-verify-now" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>${t('verify.run_verify_btn', {}, 'Run Verification Cycle')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('verify.history_title', {}, 'Verification Run History')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${history.length} verification runs</span>
          </div>

          ${
            history && history.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('verify.col_date', {}, 'Verification Date')}</th>
                    <th style="text-align:right;">${t('verify.col_tickets_closed', {}, 'Auto-Closed Tickets')}</th>
                    <th style="text-align:right;">${t('verify.col_regressions', {}, 'Regressions')}</th>
                    <th style="text-align:right;">${t('verify.col_delta', {}, 'Visibility Delta')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${history
                    .map(
                      (h) => `
                    <tr>
                      <td><strong class="num">${h.date || h.created_at}</strong></td>
                      <td data-num style="color:var(--good);font-weight:700;">+${h.closed_count || 0}</td>
                      <td data-num style="color:${h.reopened_count ? 'var(--bad)' : 'var(--muted)'};">${h.reopened_count || 0}</td>
                      <td data-num style="font-weight:700;color:var(--accent);">+${h.delta_pct || '0%'}</td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
                ${renderEmpty({
                  title: t('verify.no_history', {}, 'No Verification History'),
                  description: t('verify.no_history_desc', {}, 'After deploying action tickets to your website, run a verification cycle to measure before-and-after improvements.'),
                  actionText: t('verify.run_verify_btn', {}, 'Run Verification Cycle'),
                  onAction: () => document.getElementById('btn-run-verify-now')?.click(),
                })}
              </div>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-run-verify-now')?.addEventListener('click', async () => {
      const btn = document.getElementById('btn-run-verify-now');
      btn.disabled = true;
      try {
        const res = await projects.triggerVerify(projectId);
        toast.success(t('verify.queued', {}, 'Verification cycle initiated!'));
        ctx.pollActiveJobs();
        if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
          ctx.openTelemetry(res.job_id, 'verify');
        }
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to start verification'));
      } finally {
        btn.disabled = false;
      }
    });
  },
};
