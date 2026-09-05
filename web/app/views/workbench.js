import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { samplingModeBadge } from '../components/badge.js';
import { escapeHtml, safeHttpUrl } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const qid = ctx.params.qid || '';
    let data;
    let questions = [];
    let loadFailed = false;
    try {
      [data, questions] = await Promise.all([workspace.getWorkbench(projectId, qid), workspace.getQuestions(projectId)]);
    } catch (error) {
      console.error('Failed to load workbench:', error);
      loadFailed = true;
      data = { question: null, sources: [], samples: [] };
    }
    const question = data.question;
    const samples = data.samples || [];
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('workbench.title', {}, 'Sampling Evidence Workbench')}</h1>
            <p class="view-desc">${t('workbench.desc', {}, 'Replay recorded model answers and inspect the content sources available for the selected question.')}</p>
          </div>
          <div class="view-actions"><a href="#/engines" class="btn btn-primary btn-sm">${t('workbench.run_new_btn', {}, 'Run New Sampling')}</a></div>
        </div>
        ${loadFailed ? renderEmpty({ title: t('workbench.load_failed_title', {}, 'Could not load sampling evidence'), description: t('workbench.load_failed_desc', {}, 'Retry the workbench or check the project connection.') }) : ''}
        <div class="card" style="gap:var(--sp-3);">
          <label class="kicker" for="workbench-question">${t('workbench.question_picker', {}, 'Question')}</label>
          <select id="workbench-question" class="input" style="max-width:720px;" aria-label="${t('workbench.question_picker', {}, 'Question')}">
            <option value="">${t('workbench.all_questions', {}, 'All questions')}</option>
            ${(Array.isArray(questions) ? questions : []).map((item) => `<option value="${escapeHtml(item.id || '')}" ${item.id === qid ? 'selected' : ''}>${escapeHtml(item.id || '')} · ${escapeHtml(item.question || item.text || item.query || '')}</option>`).join('')}
          </select>
          <span class="kicker">${t('workbench.selected_q', {}, 'Selected Question')}</span>
          <strong>${escapeHtml(question?.text || t('workbench.select_prompt', {}, 'Select a question from the question bank.'))}</strong>
          <span style="font-size:var(--fs-2);color:var(--muted);">${escapeHtml(question?.id || t('workbench.no_qid', {}, 'No question ID'))}${data.sample_date ? ` | ${escapeHtml(t('workbench.latest_artifact', { date: data.sample_date }, `Latest sample artifact: ${data.sample_date}`))}` : ''}</span>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">${(data.sources || []).map((source) => `<a class="tag tag-neutral workbench-source" href="#/assets?question=${encodeURIComponent(qid)}&path=${encodeURIComponent(source.path || '')}" title="${escapeHtml(source.path)}">${escapeHtml(source.kind)}: ${escapeHtml(source.path)}</a>`).join('')}</div>
        </div>
        ${samples.length ? `<div class="card" style="display:flex;flex-wrap:wrap;gap:var(--sp-5);"><span><strong>${new Set(samples.map((s) => s.engine_code || s.engine_name)).size}</strong> ${t('workbench.models', {}, 'models')}</span><span><strong>${samples.filter((s) => s.ok && s.mentioned).length}/${samples.filter((s) => s.ok).length || 0}</strong> ${t('workbench.mentioned_summary', {}, 'mentioned')}</span><span>${escapeHtml(data.sample_date || '')}</span></div>` : ''}
        <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
          ${!loadFailed && samples.length ? samples.map((sample) => {
            const mentionedText = !sample.ok
              ? t('workbench.status_failed', {}, 'Sampling failed')
              : sample.mentioned
              ? `${t('workbench.status_mentioned', {}, 'Mentioned')}${sample.matched_identity?.text ? ` ${t('workbench.via_identity', { identity: escapeHtml(sample.matched_identity.text) }, `via "${escapeHtml(sample.matched_identity.text)}"`)}` : ''}${sample.rank ? ` ${t('workbench.at_rank', { rank: sample.rank }, `at rank ${sample.rank}`)}` : ''}`
              : t('workbench.status_not_mentioned', {}, 'Not mentioned');
            return `
            <div class="card" style="gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);">
                <strong>${escapeHtml(sample.engine_name || sample.engine_code)}</strong>
                <span class="tag ${!sample.ok ? 'pill-bad' : sample.mentioned ? 'pill-good' : 'tag-dim'}">${mentionedText}</span>
              </div>
              <span style="align-self:flex-start;">${samplingModeBadge(sample.sampling_mode_code || sample.sampling_mode)}</span>
              <div style="display:flex;gap:var(--sp-3);color:var(--muted);font-size:var(--fs-2);">
                <span>${escapeHtml(sample.sampled_at || data.sample_date || t('common.unmeasured', {}, 'Unmeasured'))}</span>
                <span>${(sample.citations || []).length} ${t('workbench.citations', {}, 'citations')}</span>
              </div>
              <details>
                <summary>${t('workbench.answer_summary', {}, 'Inspect model answer')}</summary>
                <div class="sample-answer">${escapeHtml(sample.ok ? (sample.answer || t('workbench.empty_response', {}, 'Empty model response')) : t('workbench.sampling_failed', { error: sample.error || 'Unknown provider error' }, `Sampling failed: ${sample.error || 'Unknown provider error'}`))}</div>
              </details>
              <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;"><a class="btn btn-ghost btn-sm" href="#/assets?question=${encodeURIComponent(qid)}">${t('workbench.view_assets', {}, 'View assets')}</a><a class="btn btn-ghost btn-sm" href="#/plan?question=${encodeURIComponent(qid)}">${t('workbench.open_tickets', {}, 'Open tickets')}</a></div>
              ${(sample.citations || []).length ? `<div class="sample-citations">${sample.citations.map((citation) => {
                const url = typeof citation === 'string' ? citation : citation?.url;
                const safe = safeHttpUrl(url);
                if (!safe) return '';
                let label = safe;
                try { label = new URL(safe).hostname; } catch (error) { /* safeHttpUrl already validated the value */ }
                return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
              }).join('')}</div>` : ''}
            </div>`;
          }).join('') : (!loadFailed ? renderEmpty({ title: t('workbench.no_samples_title', {}, 'No recorded samples for this question'), description: t('workbench.no_samples_desc', {}, 'Run a sampling job, then return here to inspect real responses.') }) : '')}
        </div>
      </div>`;
  },
  mounted: (ctx) => {
    document.querySelector('#workbench-question')?.addEventListener('change', (event) => {
      const next = event.target.value;
      window.location.hash = next ? `#/workbench?qid=${encodeURIComponent(next)}` : '#/workbench';
    });
  },
};
