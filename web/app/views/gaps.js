/**
 * 差异诊断与认知偏离视图 (Gaps & AI Framing)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let framing = null;
    try {
      framing = await projects.getFraming(projectId).catch(() => null);
    } catch (e) {}

    const deviations = (framing && framing.deviations) || [];

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('gaps.title', {}, 'AI Perception Gap & Framing Analysis')}</h1>
            <p class="view-desc">
              ${t('gaps.desc', {}, 'Diagnose discrepancies between how LLMs describe your brand versus official facts, entity definitions, and positioning.')}
            </p>
          </div>
        </div>

        <!-- 差异诊断卡片 -->
        <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
          <div class="card" style="gap:var(--sp-3);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('gaps.framing_summary', {}, 'AI Impression & Association Phrases')}</h3>
              <span style="font-size:var(--fs-1);color:var(--muted);">${t('gaps.source_note', {}, 'Aggregated from multi-round unprompted sampling answers')}</span>
            </div>
            <p style="color:var(--ink-2);font-size:var(--fs-3);line-height:1.6;margin:0;">
              ${(framing && framing.summary) || t('gaps.default_summary', {}, 'AI models recognize the brand in primary categories with moderate authority evidence. Fact deviations should be addressed via Wikipedia disambiguation and structured fact extraction blocks.')}
            </p>
          </div>

          <!-- 偏差明细表 -->
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('gaps.deviations_title', {}, 'Detected Fact Deviations & Hallucinations')}</h3>
            </div>

            ${
              deviations.length
                ? `
              <div class="tbl" style="overflow-x:auto;">
                <table class="table">
                  <thead>
                    <tr>
                      <th>${t('gaps.col_topic', {}, 'Entity / Topic')}</th>
                      <th>${t('gaps.col_ai_says', {}, 'What AI Models Say')}</th>
                      <th>${t('gaps.col_truth', {}, 'Official Brand Truth')}</th>
                      <th>${t('gaps.col_action', {}, 'Recommended Fix')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${deviations
                      .map(
                        (d) => `
                      <tr>
                        <td><strong>${d.topic}</strong></td>
                        <td style="color:var(--bad);">${d.ai_says}</td>
                        <td style="color:var(--good);">${d.truth}</td>
                        <td><a href="#/plan" class="tag tag-accent" style="text-decoration:none;">${d.ticket || 'View Ticket'}</a></td>
                      </tr>
                    `
                      )
                      .join('')}
                  </tbody>
                </table>
              </div>
            `
                : `
              <div style="padding:var(--sp-6);font-size:var(--fs-2);color:var(--muted);text-align:center;">
                ${t('gaps.no_critical_deviations', {}, 'No critical factual hallucinations detected in current sampling batches.')}
              </div>
            `
            }
          </div>
        </div>
      </div>
    `;
  },
};
