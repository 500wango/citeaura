/**
 * Target questions
 */

import { workspace, projects } from '../api.js';
import { t, tError } from '../i18n.js';
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
    let research = {};
    let insights = {};
    try {
      let project = null;
      [questions, expand, project, research] = await Promise.all([
        workspace.getQuestions(projectId).catch(() => []),
        workspace.getExpand(projectId).catch(() => ({})),
        projects.get(projectId).catch(() => null),
        workspace.getPromptResearch(projectId).catch(() => ({})),
      ]);
      insights = project?.insights || {};
    } catch (err) {
      console.error('Failed to load questions:', err);
    }
    const candidates = Array.isArray(expand?.candidates) ? expand.candidates : (Array.isArray(expand?.terms) ? expand.terms : []);
    const explorer = insights.prompt_explorer || {};
    const opportunityItems = Array.isArray(explorer.items) ? explorer.items : [];
    const researchItems = Array.isArray(research?.items) ? research.items : [];
    const priorityLabel = { high: 'High opportunity', medium: 'Medium opportunity', needs_sampling: 'Needs sampling', probe: 'Brand probe', monitor: 'Monitor' };

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

        <div class="card" style="gap:var(--sp-3);margin-bottom:var(--sp-4);">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div>
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${t('questions.research_title', {}, 'Prompt Research')}</h3>
              <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('questions.research_desc', {}, 'Start from a brand, category, competitor, or URL. Review intent fan-out before adding prompts to the monitoring bank.')}</p>
            </div>
            <button type="button" id="btn-run-prompt-research" class="btn btn-primary btn-sm">${t('questions.research_btn', {}, 'Research prompts')}</button>
          </div>
          ${researchItems.length ? `<div class="tbl" style="overflow-x:auto;"><table class="table"><thead><tr><th>${t('questions.col_candidate', {}, 'Prompt candidate')}</th><th>${t('questions.col_seed', {}, 'Seed')}</th><th>${t('questions.col_intent', {}, 'Intent')}</th><th>${t('questions.col_funnel_stage', {}, 'Funnel stage')}</th><th style="text-align:right;">${t('common.action', {}, 'Action')}</th></tr></thead><tbody>${researchItems.slice(0, 18).map((item) => `<tr><td style="min-width:300px;"><strong>${escapeHtml(item.text || '')}</strong></td><td><span class="tag tag-dim">${escapeHtml(item.seed || '')}</span></td><td><span class="tag tag-neutral">${escapeHtml(item.intent || '')}</span></td><td>${escapeHtml(item.funnel_stage || '')}</td><td style="text-align:right;">${item.in_question_bank ? `<span class="tag pill-good">${t('questions.in_bank', {}, 'In bank')}</span>` : `<button type="button" class="btn btn-secondary btn-sm btn-add-research" data-text="${escapeHtml(item.text || '')}" data-intent="${escapeHtml(item.intent || '')}">${t('questions.add_to_monitoring', {}, 'Add to monitoring')}</button>`}</td></tr>`).join('')}</tbody></table></div>` : `<div style="padding:var(--sp-4);background:var(--page);color:var(--muted);font-size:var(--fs-2);">${t('questions.no_research_yet', {}, 'No research run yet. Generate a fan-out to discover the questions your buyers may ask.')}</div>`}
        </div>

        <div class="card" style="padding:0;overflow:hidden;margin-bottom:var(--sp-4);">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);">
            <div>
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${t('questions.explorer_title', {}, 'Prompt Explorer')}</h3>
              <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('questions.explorer_desc', {}, 'Prioritize unprompted prompts where visibility is missing, inconsistent, or competitor-led.')}</p>
            </div>
            <span class="tag tag-neutral">${explorer.measured_count || 0}/${explorer.total_count || 0} measured</span>
          </div>
          ${opportunityItems.length ? `<div class="tbl" style="overflow-x:auto;">
            <table class="table">
              <thead><tr>
                <th>${t('questions.col_prompt', {}, 'Prompt')}</th><th>${t('questions.col_opportunity', {}, 'Opportunity')}</th><th style="text-align:right;">${t('questions.col_mention', {}, 'Mention')}</th><th>${t('questions.col_signals', {}, 'Signals')}</th><th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
              </tr></thead>
              <tbody>${opportunityItems.slice(0, 12).map((item) => {
                const interval = item.mention_interval;
                const mention = item.mention === null || item.mention === undefined ? 'Unmeasured' : `${Math.round(item.mention * 100)}%`;
                const band = interval ? `${Math.round(interval.lower * 100)}-${Math.round(interval.upper * 100)}%` : '—';
                const reasons = (item.reasons || []).slice(0, 2).join(' · ');
                const score = item.opportunity_score === null || item.opportunity_score === undefined ? '—' : `${item.opportunity_score}/100`;
                return `<tr>
                  <td style="min-width:260px;"><strong>${escapeHtml(item.text || item.id || '')}</strong><div class="num" style="color:var(--muted);font-size:var(--fs-1);margin-top:3px;">${escapeHtml(item.id || '')} · ${escapeHtml(item.group || 'General')}</div></td>
                  <td><span class="tag ${item.priority === 'high' ? 'pill-bad' : item.priority === 'medium' ? 'pill-warn' : 'tag-neutral'}">${escapeHtml(priorityLabel[item.priority] || item.priority || 'Review')}</span><div class="num" style="color:var(--muted);font-size:var(--fs-1);margin-top:3px;">${score}</div></td>
                  <td data-num><strong>${mention}</strong><div class="num" style="color:var(--muted);font-size:var(--fs-1);">95% ${band} · n=${item.samples || 0}</div></td>
                  <td style="min-width:230px;color:var(--muted);font-size:var(--fs-2);">${escapeHtml(reasons || 'No additional signal')}</td>
                  <td style="text-align:right;"><a href="#/workbench?qid=${encodeURIComponent(item.id || '')}" class="btn btn-ghost btn-sm">${t('questions.replay_btn', {}, 'Replay')}</a></td>
                </tr>`;
              }).join('')}</tbody>
            </table>
          </div>` : `<div style="padding:var(--sp-6);color:var(--muted);font-size:var(--fs-2);">${t('questions.run_sample_hint', {}, 'Run a sample to populate prompt opportunities. Unmeasured prompts are not ranked.')}</div>`}
        </div>

        ${candidates.length ? `
          <div class="card" style="gap:var(--sp-3);margin-bottom:var(--sp-4);">
            <strong>${t('questions.expansion_candidates', {}, 'Expansion candidates')}</strong>
            <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('questions.confirm_candidate_desc', {}, 'Confirm a candidate to add it to the evaluation bank.')}</p>
            ${candidates.slice(0, 12).map((item) => {
              const text = item.text || item.question || item.term || item;
              return `<div style="display:flex;justify-content:space-between;gap:var(--sp-3);align-items:center;">
                <span>${escapeHtml(text)}</span>
                <button type="button" class="btn btn-secondary btn-sm btn-accept-expand" data-text="${escapeHtml(text)}">${t('common.add', {}, 'Add')}</button>
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
                    <th>${t('questions.col_source', {}, 'Source')}</th>
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
                        <a href="#/workbench?qid=${encodeURIComponent(q.id || '')}" class="btn btn-ghost btn-sm">${t('questions.replay_btn', {}, 'Replay')}</a>
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

    const runResearch = () => {
      openModal({
        title: t('questions.research_btn', {}, 'Research prompts'),
        content: `<div style="display:flex;flex-direction:column;gap:var(--sp-3);"><p style="font-size:var(--fs-2);color:var(--muted);margin:0;">Enter one seed per line. The project brand, category, competitors, and official URL are included automatically.</p><textarea id="research-seeds" class="input" rows="5" placeholder="AI visibility platform\nGEO software"></textarea></div>`,
        confirmText: t('questions.generate_fanout_btn', {}, 'Generate fan-out'),
        onConfirm: async () => {
          const seeds = (document.getElementById('research-seeds')?.value || '').split('\n').map((value) => value.trim()).filter(Boolean).slice(0, 20);
          try {
            await workspace.runPromptResearch(projectId, { seeds });
            toast.success('Prompt research generated');
            await ctx.reloadCurrentView();
            return true;
          } catch (err) {
            toast.error(err.detail || 'Prompt research failed');
            return false;
          }
        },
      });
    };

    document.getElementById('btn-run-prompt-research')?.addEventListener('click', runResearch);

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
            toast.error(tError(err));
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

    document.querySelectorAll('.btn-add-research').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          await workspace.addQuestions(projectId, {
            items: [{
              text: button.getAttribute('data-text') || '',
              market: 'global',
              group: button.getAttribute('data-intent') || 'Research',
              source: 'prompt_research',
            }],
          });
          toast.success('Prompt added to monitoring bank');
          await ctx.reloadCurrentView();
        } catch (err) {
          toast.error(err.detail || 'Failed to add prompt');
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
