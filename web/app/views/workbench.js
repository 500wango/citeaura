import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: 'No Brand Selected' })}</div>`;
    const qid = ctx.params.qid || '';
    const data = await workspace.getWorkbench(projectId, qid).catch(() => ({ question: null, sources: [], samples: [] }));
    const question = data.question;
    const samples = data.samples || [];
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">Sampling Evidence Workbench</h1>
            <p class="view-desc">Replay recorded model answers and inspect the content sources available for the selected question.</p>
          </div>
          <div class="view-actions"><a href="#/engines" class="btn btn-primary btn-sm">Run New Sampling</a></div>
        </div>
        <div class="card" style="gap:var(--sp-3);">
          <span class="kicker">Selected Question</span>
          <strong>${question?.text || 'Select a question from the question bank.'}</strong>
          <span style="font-size:var(--fs-2);color:var(--muted);">${question?.id || 'No question ID'}${data.sample_date ? ` | Latest sample artifact: ${data.sample_date}` : ''}</span>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">${(data.sources || []).map((source) => `<span class="tag tag-neutral">${source.kind}: ${source.path}</span>`).join('')}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
          ${samples.length ? samples.map((sample) => `
            <div class="card" style="gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);">
                <strong>${sample.engine_name || sample.engine_code}</strong>
                <span class="tag ${sample.mentioned ? 'pill-good' : 'tag-dim'}">${sample.mentioned ? `Mentioned${sample.rank ? ` at rank ${sample.rank}` : ''}` : 'Not mentioned'}</span>
              </div>
              <span class="tag tag-neutral" style="align-self:flex-start;">${sample.sampling_mode}</span>
              <div class="sample-answer">${sample.ok ? (sample.answer || 'Empty model response') : `Sampling failed: ${sample.error || 'Unknown provider error'}`}</div>
              ${(sample.citations || []).length ? `<div class="sample-citations">${sample.citations.map((citation) => {
                const url = typeof citation === 'string' ? citation : citation.url;
                return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
              }).join('')}</div>` : ''}
            </div>`).join('') : renderEmpty({ title: 'No recorded samples for this question', description: 'Run a sampling job, then return here to inspect real responses.' })}
        </div>
      </div>`;
  },
  mounted: () => {},
};
