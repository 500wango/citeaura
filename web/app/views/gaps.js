import { projects } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const framing = await projects.getFraming(projectId).catch(() => null);
    const terms = framing?.terms || [];
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('gaps.title', {}, 'How models describe you')}</h1>
            <p class="view-desc">${t('gaps.desc', {}, 'Review the recurring descriptors that appear in recorded model answers. This view reflects sampled phrasing only. It does not infer factual correctness.')}</p>
          </div>
        </div>
        ${terms.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('gaps.observed_title', {}, 'Observed descriptors')}</h3>
              <span style="font-size:var(--fs-1);color:var(--muted);">${t('gaps.sample_stats', { samples: framing.sample_count || 0, mentions: framing.mentioned_samples || 0 }, `${framing.sample_count || 0} samples, ${framing.mentioned_samples || 0} mentions`)}</span>
            </div>
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>${t('gaps.col_descriptor', {}, 'Descriptor')}</th><th style="text-align:right;">${t('gaps.col_share', {}, 'Share')}</th><th>${t('gaps.col_evidence', {}, 'Evidence')}</th></tr></thead>
                <tbody>
                  ${terms.map((term) => `<tr><td><strong>${escapeHtml(term.term)}</strong></td><td data-num>${Math.round((term.share || 0) * 100)}%</td><td>${(term.evidence || []).map((item) => `${escapeHtml(item.platform_name)}: ${escapeHtml(item.excerpt)}`).join('<br>')}</td></tr>`).join('')}
                </tbody>
              </table>
            </div>
          </div>` : renderEmpty({ title: t('gaps.empty_title', {}, 'No framing descriptors yet'), description: t('gaps.empty_desc', {}, 'Run sampling first. This page only shows phrasing that appears in recorded answers.') })}
      </div>`;
  },
};
