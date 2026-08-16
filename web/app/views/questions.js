/**
 * Target questions
 */

import { workspace } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty, bindEmptyAction } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let questions = [];
    let expand = {};
    try {
      [questions, expand] = await Promise.all([
        workspace.getQuestions(projectId).catch(() => []),
        workspace.getExpand(projectId).catch(() => ({})),
      ]);
    } catch (err) {
      console.error('Failed to load questions:', err);
    }
    const candidates = Array.isArray(expand?.candidates) ? expand.candidates : (Array.isArray(expand?.terms) ? expand.terms : []);

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('questions.title', {}, 'Target Question Bank')}</h1>
            <p class="view-desc">
              ${t('questions.desc', {}, 'These questions are used on the next sample run. Edit them before sampling.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-add-question" class="btn btn-primary btn-sm">
              <span>${t('questions.add_btn', {}, 'Add Questions')}</span>
            </button>
          </div>
        </div>

        ${candidates.length ? `
          <div class="card" style="gap:var(--sp-3);margin-bottom:var(--sp-4);">
            <strong>Expansion candidates</strong>
            <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">Confirm a candidate to add it to the evaluation bank.</p>
            ${candidates.slice(0, 12).map((item) => {
              const text = item.text || item.question || item.term || item;
              return `<div style="display:flex;justify-content:space-between;gap:var(--sp-3);align-items:center;">
                <span>${escapeHtml(text)}</span>
                <button type="button" class="btn btn-secondary btn-sm btn-accept-expand" data-text="${escapeHtml(text)}">Add</button>
              </div>`;
            }).join('')}
          </div>` : ''}

        <div class="card" style="padding:0;overflow:hidden;">
          ${
            questions.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>${t('questions.col_question', {}, 'Question / Query')}</th>
                    <th>${t('questions.col_intent', {}, 'Intent / Category')}</th>
                    <th>Source</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${questions
                    .map(
                      (q) => `
                    <tr>
                      <td class="num">${escapeHtml(q.id || '')}</td>
                      <td><strong style="font-size:var(--fs-3);color:var(--ink);">${escapeHtml(q.question || q.text || q.query || q)}</strong></td>
                      <td><span class="tag tag-neutral">${escapeHtml(q.category || q.group || q.intent || 'General')}</span></td>
                      <td><span class="tag tag-dim">${escapeHtml(q.source || 'generated')}</span></td>
                      <td style="text-align:right;display:flex;gap:var(--sp-2);justify-content:flex-end;">
                        <a href="#/workbench?qid=${encodeURIComponent(q.id || '')}" class="btn btn-ghost btn-sm">Replay</a>
                        <button type="button" class="btn btn-ghost btn-sm btn-edit-question" data-id="${escapeHtml(q.id || '')}" data-text="${escapeHtml(q.text || q.question || '')}">Edit</button>
                        <button type="button" class="btn btn-ghost btn-sm btn-del-question" data-id="${escapeHtml(q.id || '')}" style="color:var(--bad);">Remove</button>
                      </td>
                    </tr>
                  `,
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

    const addQuestions = async (lines) => {
      const items = lines.map((text) => ({ text, market: 'global', group: 'Recommendation', source: 'manual' }));
      await workspace.addQuestions(projectId, { items });
      toast.success(t('questions.added_success', {}, 'Questions added successfully'));
      await ctx.reloadCurrentView();
    };

    const openAdd = () => {
      openModal({
        title: t('questions.modal_title', {}, 'Add Target Questions'),
        content: `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <p style="font-size:var(--fs-2);color:var(--muted);margin:0;">
              ${t('questions.modal_hint', {}, 'Enter one question per line. Questions will be added to the brand evaluation bank.')}
            </p>
            <textarea id="new-questions-input" class="input" rows="6" placeholder="What is the best GEO platform for SaaS?"></textarea>
          </div>
        `,
        confirmText: t('common.add', {}, 'Add to Library'),
        onConfirm: async () => {
          const lines = (document.getElementById('new-questions-input')?.value || '')
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return false;
          try {
            await addQuestions(lines);
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to add questions'));
            return false;
          }
        },
      });
    };

    document.getElementById('btn-add-question')?.addEventListener('click', openAdd);
    bindEmptyAction(document.getElementById('view-mount'), openAdd);

    document.querySelectorAll('.btn-accept-expand').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          await addQuestions([button.getAttribute('data-text')]);
        } catch (err) {
          toast.error(err.detail || 'Failed to add candidate');
        }
      });
    });

    document.querySelectorAll('.btn-edit-question').forEach((button) => {
      button.addEventListener('click', () => {
        const questionId = button.getAttribute('data-id');
        openModal({
          title: 'Edit question',
          content: `<textarea id="edit-question-text" class="input" rows="4">${escapeHtml(button.getAttribute('data-text') || '')}</textarea>`,
          confirmText: 'Save',
          onConfirm: async () => {
            const text = document.getElementById('edit-question-text')?.value.trim();
            if (!text) return false;
            try {
              await workspace.updateQuestion(projectId, questionId, { text });
              toast.success('Question updated');
              await ctx.reloadCurrentView();
              return true;
            } catch (err) {
              toast.error(err.detail || 'Failed to update question');
              return false;
            }
          },
        });
      });
    });

    document.querySelectorAll('.btn-del-question').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          await workspace.deleteQuestion(projectId, button.getAttribute('data-id'));
          toast.success('Question removed');
          await ctx.reloadCurrentView();
        } catch (err) {
          toast.error(err.detail || 'Failed to remove question');
        }
      });
    });
  },
};
