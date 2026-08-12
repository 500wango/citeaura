import { projects } from '../api.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: 'No Brand Selected' })}</div>`;
    const framing = await projects.getFraming(projectId).catch(() => null);
    const terms = framing?.terms || [];
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">AI Framing Analysis</h1>
            <p class="view-desc">Review the recurring descriptors that appear in recorded model answers. This view reflects sampled phrasing only. It does not infer factual correctness.</p>
          </div>
        </div>
        ${terms.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">Observed descriptors</h3>
              <span style="font-size:var(--fs-1);color:var(--muted);">${framing.sample_count || 0} samples, ${framing.mentioned_samples || 0} mentions</span>
            </div>
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>Descriptor</th><th style="text-align:right;">Share</th><th>Evidence</th></tr></thead>
                <tbody>
                  ${terms.map((term) => `<tr><td><strong>${term.term}</strong></td><td data-num>${Math.round((term.share || 0) * 100)}%</td><td>${(term.evidence || []).map((item) => `${item.platform_name}: ${item.excerpt}`).join('<br>')}</td></tr>`).join('')}
                </tbody>
              </table>
            </div>
          </div>` : renderEmpty({ title: 'No framing descriptors yet', description: 'Run sampling first. This page only shows phrasing that appears in recorded answers.' })}
      </div>`;
  },
};
