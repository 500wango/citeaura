import { workspace, projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const blueprint = await workspace.getBlueprint(projectId).catch(() => ({}));
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
            <button type="button" id="btn-build-blueprint" class="btn btn-secondary btn-sm">${t('blueprint.rebuild_map', {}, 'Rebuild map')}</button>
          </div>
        </div>
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
                    <td>${channel.covered ? t('blueprint.status_covered', {}, 'Covered') : (channel.coverage_status || t('blueprint.status_gap', {}, 'Gap'))}</td>
                    <td>${escapeHtml(channel.why || '')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
          </div>` : renderEmpty({ title: t('blueprint.empty_title', {}, 'No blueprint yet'), description: t('blueprint.empty_desc', {}, 'Run Autopilot or rebuild the channel map after the first audit.') })}
      </div>`;
  },
  mounted: (ctx) => {
    document.getElementById('btn-build-blueprint')?.addEventListener('click', async () => {
      try {
        const res = await projects.triggerAction(ctx.activeProjectId, 'blueprint');
        toast.success(t('blueprint.rebuild_queued', {}, 'Blueprint rebuild queued'));
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'blueprint');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || t('blueprint.rebuild_failed', {}, 'Failed to rebuild blueprint')));
      }
    });
  },
};
