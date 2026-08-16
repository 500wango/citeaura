/**
 * AI  (Engines & Sample Replay)
 */

import { projects, workspace } from '../api.js?v=3.4';
import { openModal } from '../components/modal.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { samplingModeBadge, statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let enginesData = null;
    let samples = [];
    let sampleCohort = null;

    try {
      enginesData = await projects.getEngines(projectId).catch(() => null);
      if (enginesData && String(enginesData.project_id) !== String(projectId)) {
        throw new Error('Project response mismatch');
      }
      const sampleArtifact = enginesData?.sample_artifact || enginesData?.date;
      if (sampleArtifact) {
        const samplesData = await projects.getSamples(projectId, sampleArtifact).catch(() => null);
        if (samplesData && String(samplesData.project_id) !== String(projectId)) {
          throw new Error('Sample response project mismatch');
        }
        sampleCohort = samplesData;
        samples = samplesData?.samples || [];
      }
    } catch (err) {
      console.error('Failed to load engines data:', err);
      enginesData = null;
      samples = [];
      sampleCohort = null;
    }

    const engines = (enginesData && enginesData.engines) || [];
    const trend = (enginesData && enginesData.measurement_quality && enginesData.measurement_quality.trend) || {};
    const trendNote = trend.status === 'noteworthy'
      ? `${trend.label || 'Trend'} ${trend.delta_pp != null ? `(${trend.delta_pp} pp)` : ''}`
      : (trend.label || 'Single-round observation. Two comparable periods are required before calling a trend.');

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('engines.title', {}, 'AI Engine Visibility Matrix')}</h1>
            <p class="view-desc">
              ${t('engines.desc', {}, 'Unified visibility measurement across parametric knowledge, search-grounded models, and manual interface sampling.')}
              <span style="display:block;margin-top:4px;">${trendNote}</span>
            </p>
          </div>
          <div class="view-actions">
            <a href="#/engine-settings" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>
              <span>${t('engines.configure_keys', {}, 'Configure API Keys')}</span>
            </a>
            <button type="button" id="btn-import-sheet" class="btn btn-secondary btn-sm">
              <span>Import product-surface sheet</span>
            </button>
            <button type="button" id="btn-trigger-sample" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('engines.sample_now', {}, 'Sample Matrix Now')}</span>
            </button>
          </div>
        </div>

        <!-- Engine Visibility Matrix -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('engines.matrix_head', {}, 'Monitored Model Engines')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${engines.length} ${t('common.engines_total', {}, 'engines configured')}</span>
          </div>

          ${
            engines.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('engines.col_engine', {}, 'Engine')}</th>
                    <th>${t('engines.col_mode', {}, 'Sampling Mode')}</th>
                    <th style="text-align:right;">${t('engines.col_mention_rate', {}, 'Mention Rate')}</th>
                    <th style="text-align:right;">${t('engines.col_avg_rank', {}, 'Avg Rank')}</th>
                    <th style="text-align:right;">${t('engines.col_citation_share', {}, 'Citation Share')}</th>
                    <th style="text-align:right;">${t('engines.col_samples', {}, 'Samples')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${engines
                    .map(
                      (eng) => `
                    <tr>
                      <td>
                        <div style="display:flex;align-items:center;gap:var(--sp-2);">
                          <strong style="font-size:var(--fs-3);">${escapeHtml(eng.engine_name || eng.engine_code)}</strong>
                          <span style="font-family:var(--font-mono);font-size:11px;color:var(--muted);">${eng.engine_code}</span>
                        </div>
                      </td>
                      <td>${samplingModeBadge(eng.sampling_mode)}</td>
                      <td data-num style="font-size:var(--fs-4);font-weight:700;color:var(--ink);">
                        ${eng.mention_rate !== null && eng.mention_rate !== undefined ? `${Math.round(eng.mention_rate * 100)}%` : 'Unmeasured'}
                      </td>
                      <td data-num style="font-weight:600;">
                        ${eng.median_rank !== null && eng.median_rank !== undefined ? `#${Number(eng.median_rank).toFixed(1)}` : 'Unmeasured'}
                      </td>
                      <td data-num>
                        ${eng.citation_share !== null && eng.citation_share !== undefined ? `${Math.round(eng.citation_share * 100)}%` : 'Unmeasured'}
                      </td>
                      <td data-num>
                        ${eng.sample_count || 0}
                      </td>
                      <td>
                        ${statusPill(eng.sample_count ? 'good' : 'idle', eng.sample_count ? 'Measured' : 'Unmeasured')}
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);">${t('engines.no_engines_msg', {}, 'No engine data available. Please configure API keys and run a sample.')}</div>`
          }
        </div>

        <!-- Raw Sample Answers Replay -->
        <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--sp-3);">
            <div>
              <h3 style="font-size:var(--fs-5);font-weight:700;margin:0;">${t('engines.replay_title', {}, 'Raw AI Sample Answers & Citations')}</h3>
              <p style="color:var(--muted);font-size:var(--fs-2);margin-top:2px;">
                ${t('engines.replay_desc', {}, 'Inspect exact prompt inputs, generated model responses, and cited source URLs.')}
              </p>
            </div>
            <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">
              ${enginesData?.question_set_version ? `<span class="tag tag-neutral">Question set ${enginesData.question_set_version}</span>` : ''}
              ${sampleCohort?.excluded_sample_count ? `<span class="tag tag-dim">${sampleCohort.excluded_sample_count} historical sample${sampleCohort.excluded_sample_count === 1 ? '' : 's'} excluded</span>` : ''}
            </div>
          </div>

          ${
            samples && samples.length
              ? `
            <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
              ${samples
                .map(
                  (s, idx) => {
                    const matchedIdentity = s.analysis?.matched_identity?.text || s.analysis?.matched_identity?.value;
                    const mentionBadge = s.analysis?.brand_mentioned
                      ? `<span class="tag pill-good">Mentioned${matchedIdentity ? ` via "${matchedIdentity}"` : ''}</span>`
                      : '<span class="tag tag-dim">Not Mentioned</span>';
                    return `
                <div class="sample-replay-card">
                  <div class="sample-head">
                    <div style="display:flex;align-items:center;gap:var(--sp-2);">
                      <strong class="sample-model-tag">${s.platform_name || s.platform || 'AI Model'}</strong>
                      ${samplingModeBadge(s.sample_mode === 'manual' || s.terminal === 'web' ? 'Manual - Product interface' : (s.search_enabled ? 'API - Search grounded' : 'API - Parametric knowledge'))}
                      ${mentionBadge}
                    </div>
                    <span style="font-family:var(--font-mono);font-size:11px;color:var(--muted);">${s.date || ''}</span>
                  </div>

                  <div class="sample-query">${escapeHtml(s.question || 'Question unavailable')}</div>
                  <div class="sample-answer">${escapeHtml(s.ok ? (s.answer || 'Empty model response') : `Sampling failed: ${s.error || 'Unknown provider error'}`)}</div>

                  ${
                    s.citations && s.citations.length
                      ? `
                    <div class="sample-citations">
                      <span style="color:var(--muted);font-weight:600;">Citations:</span>
                      ${s.citations
                        .map(
                          (c) => {
                            const url = typeof c === 'string' ? c : c.url;
                            return `
                        <a href="${url}" target="_blank" rel="noopener noreferrer" class="tag tag-neutral num" style="text-decoration:none;">
                          ${url.replace(/^https?:\/\//, '').slice(0, 32)}...
                        </a>
                      `; }
                        )
                        .join('')}
                    </div>
                  `
                      : ''
                  }
                </div>
              `; }
                )
                .join('')}
            </div>
          `
              : `<div class="card" style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
                ${t('engines.no_samples_yet', {}, 'No answer samples collected for this date. Run a sampling task to inspect raw AI responses.')}
              </div>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-import-sheet')?.addEventListener('click', () => {
      openModal({
        title: 'Import product-surface sample sheet',
        content: `<div class="field"><label>Filename</label><input id="import-sheet-name" class="input" value="manual.md"></div>
          <div class="field"><label>Sheet text</label><textarea id="import-sheet-text" class="input" rows="10" placeholder="### q001 · Question"></textarea></div>`,
        confirmText: 'Import',
        onConfirm: async () => {
          try {
            await workspace.importSamples(projectId, {
              file: document.getElementById('import-sheet-name')?.value || 'manual.md',
              text: document.getElementById('import-sheet-text')?.value || '',
            });
            toast.success('Sample sheet imported');
            await ctx.reloadCurrentView();
            return true;
          } catch (err) {
            toast.error(err.detail || 'Import failed');
            return false;
          }
        },
      });
    });
    const sampleBtn = document.getElementById('btn-trigger-sample');
    if (sampleBtn) {
      sampleBtn.addEventListener('click', async () => {
        sampleBtn.disabled = true;
        try {
          const res = await projects.triggerSample(projectId);
          toast.success(t('engines.sample_queued', {}, 'Sampling task queued across matrix!'));
          ctx.pollActiveJobs();
          if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'sample');
          }
        } catch (err) {
          if (err.error === 'project_questions_required') {
            ctx.navigate('#/questions');
            return;
          }
          toast.error(t(err.error, {}, err.detail || 'Sampling task failed to start'));
        } finally {
          sampleBtn.disabled = false;
        }
      });
    }
  },
};
