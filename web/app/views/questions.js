/**
 *  (Questions)
 */

import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let questions = [];
    try {
      questions = await workspace.getQuestions(projectId).catch(() => []);
    } catch (err) {
      console.error('Failed to load questions:', err);
    }

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('questions.title', {}, 'Target Question Bank')}</h1>
            <p class="view-desc">
              ${t('questions.desc', {}, 'High-intent search questions mapped from brand core entities, user pain points, and competitor queries.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-add-question" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('questions.add_btn', {}, 'Add Questions')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          ${
            questions.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>${t('questions.col_question', {}, 'Question / Query')}</th>
                    <th>${t('questions.col_intent', {}, 'Intent / Category')}</th>
                    <th>${t('questions.col_market', {}, 'Language')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${questions
                    .map(
                      (q, idx) => `
                    <tr>
                      <td class="num" style="color:var(--muted);">${idx + 1}</td>
                      <td>
                        <strong style="font-size:var(--fs-3);color:var(--ink);">${q.question || q.text || q.query || q}</strong>
                      </td>
                      <td>
                        <span class="tag tag-neutral">${q.category || q.intent || 'General'}</span>
                      </td>
                      <td>
                        <span class="tag tag-dim num">${q.market || 'Universal'}</span>
                      </td>
                      <td style="text-align:right;">
                        <a href="#/workbench?qid=${encodeURIComponent(q.id)}" class="btn btn-ghost btn-sm">
                          ${t('questions.test_in_workbench', {}, 'Test in Workbench')} →
                        </a>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);">
                ${renderEmpty({
                  title: t('questions.empty_title', {}, 'No Questions in Library'),
                  description: t('questions.empty_desc', {}, 'Add user search queries to evaluate brand presence across LLMs.'),
                  actionText: t('questions.add_btn', {}, 'Add Questions'),
                  onAction: () => document.getElementById('btn-add-question')?.click(),
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

    const addBtn = document.getElementById('btn-add-question');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        const formHtml = `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <p style="font-size:var(--fs-2);color:var(--muted);margin:0;">
              ${t('questions.modal_hint', {}, 'Enter one question per line. Questions will be added to the brand evaluation bank.')}
            </p>
            <textarea id="new-questions-input" class="input" rows="6" placeholder="What is the best GEO platform for SaaS?&#10;How does CiteAura compare to competitors?"></textarea>
          </div>
        `;

        openModal({
          title: t('questions.modal_title', {}, 'Add Target Questions'),
          content: formHtml,
          confirmText: t('common.add', {}, 'Add to Library'),
          onConfirm: async () => {
            const val = document.getElementById('new-questions-input')?.value || '';
            const lines = val
              .split('\n')
              .map((l) => l.trim())
              .filter(Boolean);
            if (!lines.length) return false;

            try {
              const items = lines.map((text) => ({ text, market: 'global', group: 'Recommendation' }));
              await workspace.addQuestions(projectId, { items });
              toast.success(t('questions.added_success', {}, 'Questions added successfully'));
              ctx.navigate('#/questions');
              return true;
            } catch (err) {
              toast.error(t(err.error, {}, err.detail || 'Failed to add questions'));
              return false;
            }
          },
        });
      });
    }
  },
};
