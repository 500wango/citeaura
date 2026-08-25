import { workspace } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { samplingModeBadge } from '../components/badge.js';
import { escapeHtml, safeHttpUrl } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const qid = ctx.params.qid || '';
    const data = await workspace.getWorkbench(projectId, qid).catch(() => ({ question: null, sources: [], samples: [] }));
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
        <div class="card" style="gap:var(--sp-3);">
          <span class="kicker">${t('workbench.selected_q', {}, 'Selected Question')}</span>
          <strong>${escapeHtml(question?.text || t('workbench.select_prompt', {}, 'Select a question from the question bank.'))}</strong>
          <span style="font-size:var(--fs-2);color:var(--muted);">${escapeHtml(question?.id || t('workbench.no_qid', {}, 'No question ID'))}${data.sample_date ? ` | ${escapeHtml(t('workbench.latest_artifact', { date: data.sample_date }, `Latest sample artifact: ${data.sample_date}`))}` : ''}</span>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">${(data.sources || []).map((source) => `<span class="tag tag-neutral">${escapeHtml(source.kind)}: ${escapeHtml(source.path)}</span>`).join('')}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
          ${samples.length ? samples.map((sample) => {
            const mentionedText = sample.mentioned
              ? `${t('workbench.status_mentioned', {}, 'Mentioned')}${sample.matched_identity?.text ? ` ${t('workbench.via_identity', { identity: escapeHtml(sample.matched_identity.text) }, `via "${escapeHtml(sample.matched_identity.text)}"`)}` : ''}${sample.rank ? ` ${t('workbench.at_rank', { rank: sample.rank }, `at rank ${sample.rank}`)}` : ''}`
              : t('workbench.status_not_mentioned', {}, 'Not mentioned');
            return `
            <div class="card" style="gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);">
                <strong>${escapeHtml(sample.engine_name || sample.engine_code)}</strong>
                <span class="tag ${sample.mentioned ? 'pill-good' : 'tag-dim'}">${mentionedText}</span>
              </div>
              <span style="align-self:flex-start;">${samplingModeBadge(sample.sampling_mode_code || sample.sampling_mode)}</span>
              <div class="sample-answer">${escapeHtml(sample.ok ? (sample.answer || t('workbench.empty_response', {}, 'Empty model response')) : t('workbench.sampling_failed', { error: sample.error || 'Unknown provider error' }, `Sampling failed: ${sample.error || 'Unknown provider error'}`))}</div>
              ${(sample.citations || []).length ? `<div class="sample-citations">${sample.citations.map((citation) => {
                const url = typeof citation === 'string' ? citation : citation?.url;
                const safe = safeHttpUrl(url);
                if (!safe) return '';
                return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safe)}</a>`;
              }).join('')}</div>` : ''}
            </div>`;
          }).join('') : renderEmpty({ title: t('workbench.no_samples_title', {}, 'No recorded samples for this question'), description: t('workbench.no_samples_desc', {}, 'Run a sampling job, then return here to inspect real responses.') })}
        </div>
      </div>`;
  },
  mounted: () => {},
};
