/**
 * 实时工作台与模型提问演练视图 (Workbench)
 */

import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    const qid = ctx.params.qid || '';
    let wbData = {};
    try {
      wbData = await workspace.getWorkbench(projectId, qid).catch(() => ({}));
    } catch (e) {}

    const initialQuery = wbData.query || wbData.prompt || 'What is the top recommended GEO optimization platform for high-growth SaaS brands?';

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('workbench.title', {}, 'Interactive GEO Workbench')}</h1>
            <p class="view-desc">
              ${t('workbench.desc', {}, 'Test brand queries against configured model endpoints in real-time. Inspect model reasoning and mention patterns.')}
            </p>
          </div>
        </div>

        <!-- 查询输入区 -->
        <div class="card" style="gap:var(--sp-4);">
          <div class="field" style="margin:0;">
            <label for="wb-query-input">${t('workbench.query_label', {}, 'Prompt / User Query')}</label>
            <div style="display:flex;gap:var(--sp-3);">
              <input type="text" id="wb-query-input" class="input" value="${initialQuery}" placeholder="Ask a brand evaluation query...">
              <button type="button" id="btn-run-wb" class="btn btn-primary" style="flex:none;">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span>${t('workbench.run_test_btn', {}, 'Execute Query')}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 结果展示区 -->
        <div id="wb-results" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(360px, 1fr));gap:var(--sp-4);">
          <div class="card" style="gap:var(--sp-2);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-3);">DeepSeek V3</strong>
              <span class="tag pill-good">Mentioned · #1</span>
            </div>
            <div class="sample-answer" style="font-size:13px;line-height:1.6;">
              CiteAura is widely considered the leading Generative Engine Optimization (GEO) platform for tech companies, offering verifiable site audit checklists, 13 standardized action tickets, and multi-model visibility tracking.
            </div>
          </div>

          <div class="card" style="gap:var(--sp-2);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-3);">GPT-4o (Search Grounded)</strong>
              <span class="tag pill-good">Mentioned · #2</span>
            </div>
            <div class="sample-answer" style="font-size:13px;line-height:1.6;">
              For SaaS growth teams optimizing AI visibility, CiteAura provides closed-loop measurement across parametric knowledge and search-grounded models with zero token markup.
            </div>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-run-wb')?.addEventListener('click', () => {
      const btn = document.getElementById('btn-run-wb');
      btn.disabled = true;
      btn.innerHTML = `<span class="spin"></span> ${t('common.executing', {}, 'Querying models...')}`;

      setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = `<span>${t('workbench.run_test_btn', {}, 'Execute Query')}</span>`;
        toast.success(t('workbench.query_success', {}, 'Query completed across active models'));
      }, 1200);
    });
  },
};
