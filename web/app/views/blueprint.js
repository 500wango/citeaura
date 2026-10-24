import { workspace, projects } from '../api.js';
import { t, tError } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const [blueprint, jobs] = await Promise.all([
      workspace.getBlueprint(projectId).catch(() => ({})),
      projects.getJobs(projectId).catch(() => []),
    ]);
    const activeJob = Array.isArray(jobs) ? jobs.find((job) => ['queued', 'running'].includes(job.status)) : null;
    const isViewer = ctx.role === 'viewer';
    const actionBlocked = Boolean(activeJob) || isViewer;
    const actionBlockReason = isViewer
      ? t('plan.viewer_read_only', {}, 'Viewer access: you can inspect evidence but cannot change tickets or plans.')
      : t('project_job_already_running', {}, 'A job is already running for this brand.');
    const channels = blueprint.channels || [];
    const coverage = blueprint.coverage || {};
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('blueprint.title', {}, 'Channel Blueprint')}</h1>
            <p class="view-desc">${t('blueprint.desc', {}, 'Priority channels and coverage from the current project build map.')}</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-build-blueprint" class="btn btn-secondary btn-sm" ${actionBlocked ? `disabled title="${escapeHtml(actionBlockReason)}"` : ''}>${t('blueprint.rebuild_map', {}, 'Rebuild map')}</button>
          </div>
        </div>
        ${isViewer ? `<div class="read-only-note" role="status">${escapeHtml(actionBlockReason)}</div>` : ''}
        ${activeJob ? `<div class="job-block-note" role="status"><span class="status-dot"></span>${escapeHtml(t('project_job_already_running', {}, 'A job is already running for this brand.'))} ${escapeHtml(activeJob.action || '')} · ${escapeHtml(activeJob.status || '')}</div>` : ''}
        <div class="card" style="margin-bottom:var(--sp-4);">
          ${t('blueprint.covered_stat', {
            covered: Number(coverage.channel_covered || 0),
            total: Number(coverage.channel_total || channels.length || 0),
            manual: Number(coverage.channel_manual || 0),
          }, `Covered ${Number(coverage.channel_covered || 0)} / ${Number(coverage.channel_total || channels.length || 0)} · Manual ${Number(coverage.channel_manual || 0)}`)}
        </div>
        ${channels.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div class="tbl"><table class="table">
              <thead><tr><th>${t('blueprint.col_priority', {}, 'Priority')}</th><th>${t('blueprint.col_channel', {}, 'Channel')}</th><th>${t('blueprint.col_coverage', {}, 'Coverage')}</th><th>${t('blueprint.col_why', {}, 'Why')}</th></tr></thead>
              <tbody>
                ${channels.map((channel) => `
                  <tr>
                    <td>${escapeHtml(channel.priority || '')}</td>
                    <td><strong>${escapeHtml(channel.name || channel.id)}</strong></td>
                    <td>${escapeHtml(channel.covered ? t('blueprint.status_covered', {}, 'Covered') : (channel.coverage_status || t('blueprint.status_gap', {}, 'Gap')))}</td>
                    <td>${escapeHtml(channel.why || '')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
          </div>` : renderEmpty({ title: t('blueprint.empty_title', {}, 'No blueprint yet'), description: t('blueprint.empty_desc', {}, 'Run Autopilot or rebuild the channel map after the first audit.') })}
      </div>`;
  },
  mounted: (ctx) => {
    const button = document.getElementById('btn-build-blueprint');
    if (button && !button.disabled) button.addEventListener('click', async () => {
      try {
        const res = await projects.triggerAction(ctx.activeProjectId, 'blueprint');
        toast.success(t('blueprint.rebuild_queued', {}, 'Blueprint rebuild queued'));
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'blueprint');
      } catch (err) {
        toast.error(tError(err, 'blueprint.rebuild_failed'));
      }
    });
  },
};
