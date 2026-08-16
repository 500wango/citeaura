import { workspace, projects } from '../api.js?v=3.4';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: 'No Brand Selected' })}</div>`;
    const blueprint = await workspace.getBlueprint(projectId).catch(() => ({}));
    const channels = blueprint.channels || [];
    const coverage = blueprint.coverage || {};
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">Channel Blueprint</h1>
            <p class="view-desc">Priority channels and coverage from the current project build map.</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-build-blueprint" class="btn btn-secondary btn-sm">Rebuild map</button>
          </div>
        </div>
        <div class="card" style="margin-bottom:var(--sp-4);">
          Covered ${Number(coverage.channel_covered || 0)} / ${Number(coverage.channel_total || channels.length || 0)}
          · Manual ${Number(coverage.channel_manual || 0)}
        </div>
        ${channels.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div class="tbl"><table class="table">
              <thead><tr><th>Priority</th><th>Channel</th><th>Coverage</th><th>Why</th></tr></thead>
              <tbody>
                ${channels.map((channel) => `
                  <tr>
                    <td>${escapeHtml(channel.priority || '')}</td>
                    <td><strong>${escapeHtml(channel.name || channel.id)}</strong></td>
                    <td>${channel.covered ? 'Covered' : (channel.coverage_status || 'Gap')}</td>
                    <td>${escapeHtml(channel.why || '')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
          </div>` : renderEmpty({ title: 'No blueprint yet', description: 'Run Autopilot or rebuild the channel map after the first audit.' })}
      </div>`;
  },
  mounted: (ctx) => {
    document.getElementById('btn-build-blueprint')?.addEventListener('click', async () => {
      try {
        const res = await projects.triggerAction(ctx.activeProjectId, 'blueprint');
        toast.success('Blueprint rebuild queued');
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'blueprint');
      } catch (err) {
        toast.error(err.detail || 'Failed to rebuild blueprint');
      }
    });
  },
};
