/**
 * AI  (Engines & Sample Replay)
 */

import { projects, workspace } from '../api.js?v=3.5';
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
    let sampleEstimate = null;

    try {
      [enginesData, sampleEstimate] = await Promise.all([
        projects.getEngines(projectId).catch(() => null),
        projects.estimateSample(projectId).catch(() => null),
      ]);
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
    const modeKey = (mode) => {
      const n = String(mode || '').toLowerCase();
      if (n.includes('manual') || n.includes('surface') || n.includes('人工')) return 'manual';
      if (n.includes('search') || n.includes('ground') || n.includes('retrieval') || n.includes('联网')) return 'search';
      if (n.includes('param') || n.includes('model') || n.includes('参数')) return 'parametric';
      return 'other';
    };
    const modeGroups = [
      { key: 'search', title: 'API · Web-grounded retrieval', hint: 'Official search tools. This is not ChatGPT Search or Google AI Overviews.' },
      { key: 'parametric', title: 'API · Model knowledge', hint: 'Provider APIs with no live retrieval.' },
      { key: 'manual', title: 'Manual · Product surface', hint: 'Answers pasted from ChatGPT, Claude.ai, or Google AI Overviews.' },
    ];
    const grouped = Object.fromEntries(modeGroups.map((group) => [group.key, engines.filter((eng) => modeKey(eng.sampling_mode) === group.key)]));
    grouped.other = engines.filter((eng) => modeKey(eng.sampling_mode) === 'other');
    const mq = (enginesData && enginesData.measurement_quality) || {};
    const confidence = mq.confidence || mq;
    const readiness = (enginesData && enginesData.readiness) || {};
    const questionReadiness = readiness.question || {};
    const questionGaps = Array.isArray(questionReadiness.gaps) ? questionReadiness.gaps : [];
    const providerObservability = enginesData?.provider_observability?.platforms || {};
    const samplingReceipt = enginesData?.sampling_receipt || null;
    const limitations = confidence.limitations || mq.limitations || [];
    const trend = mq.trend || {};
    const attribution = mq.attribution || {};
    const trendNote = trend.status === 'noteworthy'
      ? `${trend.label || 'Trend'} ${trend.delta_pp != null ? `(${trend.delta_pp} pp)` : ''}`
      : (trend.label || 'Single-round observation. Two comparable periods are required before calling a trend.');
    const renderEngineTable = (rows) => `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('engines.col_engine', {}, 'Engine')}</th>
                    <th>${t('engines.col_mode', {}, 'Sampling Mode')}</th>
                    <th style="text-align:right;">${t('engines.col_mention_rate', {}, 'Mention Rate')}</th>
                    <th style="text-align:right;">95% Interval</th>
                    <th style="text-align:right;">${t('engines.col_avg_rank', {}, 'Avg Rank')}</th>
                    <th style="text-align:right;">${t('engines.col_citation_share', {}, 'Citation Share')}</th>
                    <th style="text-align:right;">${t('engines.col_samples', {}, 'Samples')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows.map((eng) => `
                    <tr>
                      <td>
                        <div style="display:flex;align-items:center;gap:var(--sp-2);">
                          <strong style="font-size:var(--fs-3);">${escapeHtml(eng.provider_name || eng.engine_name || eng.engine_code)}</strong>
                          <span style="font-family:var(--font-mono);font-size:11px;color:var(--muted);">${escapeHtml(eng.engine_code || '')}</span>
                          ${eng.model_id ? `<span style="font-family:var(--font-mono);font-size:11px;color:var(--muted);">${escapeHtml(eng.model_id)}</span>` : ''}
                        </div>
                      </td>
                      <td>${samplingModeBadge(eng.sampling_mode)}</td>
                      <td data-num style="font-size:var(--fs-4);font-weight:700;color:var(--ink);">
                        ${eng.mention_rate !== null && eng.mention_rate !== undefined ? `${Math.round(eng.mention_rate * 100)}%` : 'Unmeasured'}
                      </td>
                      <td data-num style="font-family:var(--font-mono);font-size:var(--fs-1);">
                        ${eng.mention_interval
                          ? `${Math.round(eng.mention_interval.lower * 100)}-${Math.round(eng.mention_interval.upper * 100)}%`
                          : 'Unmeasured'}
                      </td>
                      <td data-num style="font-weight:600;">
                        ${eng.median_rank !== null && eng.median_rank !== undefined ? `#${Number(eng.median_rank).toFixed(1)}` : 'Unmeasured'}
                      </td>
                      <td data-num>
                        ${eng.citation_share !== null && eng.citation_share !== undefined ? `${Math.round(eng.citation_share * 100)}%` : 'Unmeasured'}
                      </td>
                      <td data-num>${eng.sample_count || 0}</td>
                      <td>
                        ${statusPill(eng.sample_count ? 'good' : 'idle', eng.sample_count ? 'Measured' : 'Unmeasured')}
                        ${providerObservability[eng.engine_code]?.failed ? `<span class="tag tag-dim">${providerObservability[eng.engine_code].failed} failed</span>` : ''}
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>`;

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
            <button type="button" id="btn-import-surface" class="btn btn-secondary btn-sm">
              <span>${t('engines.log_surface_answer', {}, 'Log product-surface answer')}</span>
            </button>
            <button type="button" id="btn-trigger-sample" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('engines.sample_now', {}, 'Sample Matrix Now')}</span>
            </button>
            ${questionGaps.length ? `<button type="button" id="btn-fill-question-gaps" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
              <span>Fill ${questionGaps.length} cohort gap${questionGaps.length === 1 ? '' : 's'}</span>
            </button>` : ''}
          </div>
        </div>

        ${limitations.length ? `<div class="card" style="padding:var(--sp-4);border-color:var(--line);">
          <strong style="display:block;margin-bottom:6px;">${t('engines.measurement_limited_title', {}, 'Measurement is a limited baseline')}</strong>
          <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">
            ${escapeHtml(limitations.join(' '))} Configure at least two built-in engines and collect 20 samples before publishing a mention rate. Do not mix these rows into one score.
          </p>
        </div>` : ''}

        <div class="card" style="padding:var(--sp-4);border-color:var(--line);">
          <div style="display:flex;justify-content:space-between;gap:var(--sp-4);align-items:flex-start;flex-wrap:wrap;">
            <div>
              <strong style="display:block;margin-bottom:6px;">${t('engines.evidence_readiness_title', {}, 'Evidence readiness')}</strong>
              <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">
                ${escapeHtml(questionReadiness.label || 'Question-level evidence is not measured yet')}
                ${questionReadiness.total ? ` · ${questionReadiness.sufficient || 0}/${questionReadiness.total} questions meet the minimum in every provider/mode cohort` : ''}
              </p>
            </div>
            ${questionGaps.length ? '<span class="tag tag-warn">${t('engines.per_question_evidence_limited', {}, 'Per-question evidence limited')}</span>' : '<span class="tag pill-good">${t('engines.question_evidence_ready', {}, 'Question evidence ready')}</span>'}
          </div>
        </div>

        ${samplingReceipt ? `<div class="card" style="padding:var(--sp-4);border-color:var(--line);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div>
              <strong style="display:block;margin-bottom:4px;">${t('engines.worker_sampling_receipt', {}, 'Worker sampling receipt')}</strong>
              <span style="font-size:var(--fs-2);color:var(--muted);">Asynchronous execution evidence; credentials are never shown.</span>
            </div>
            <span class="tag ${samplingReceipt.status === 'succeeded' ? 'pill-good' : 'tag-warn'}">${escapeHtml(samplingReceipt.status || 'Not recorded')}</span>
          </div>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-top:var(--sp-3);">
            <span class="tag tag-neutral">${Number(samplingReceipt.successful_samples || 0)} successful</span>
            <span class="tag tag-dim">${Number(samplingReceipt.failed_samples || 0)} failed</span>
            <span class="tag tag-dim">${Number((samplingReceipt.skipped_platforms || []).length)} skipped platforms</span>
          </div>
        </div>` : ''}

        <div class="card" style="padding:var(--sp-4);border-color:var(--line);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><strong style="display:block;margin-bottom:4px;">${t('engines.comparable_period_title', {}, 'Comparable period analysis')}</strong><span style="font-size:var(--fs-2);color:var(--muted);">${escapeHtml(attribution.label || 'No comparable period')} · ${escapeHtml(attribution.method || 'Fixed measurement identity required')}</span></div>
            <span class="tag ${attribution.ready ? 'pill-good' : 'tag-dim'}">${attribution.ready ? 'Attribution-ready baseline' : 'Do not attribute yet'}</span>
          </div>
          ${attribution.comparisons?.length ? `<div class="tbl" style="overflow-x:auto;margin-top:var(--sp-3);"><table class="table"><thead><tr><th>${t('engines.col_provider', {}, 'Provider')}</th><th style="text-align:right;">${t('engines.col_previous', {}, 'Previous')}</th><th style="text-align:right;">${t('engines.col_current', {}, 'Current')}</th><th style="text-align:right;">${t('engines.col_delta', {}, 'Delta')}</th></tr></thead><tbody>${attribution.comparisons.map((item) => `<tr><td>${escapeHtml(item.engine_code || '')}</td><td data-num>${Math.round(Number(item.previous_rate || 0) * 100)}%</td><td data-num>${Math.round(Number(item.current_rate || 0) * 100)}%</td><td data-num>${Number(item.delta_pp || 0).toFixed(1)} pp</td></tr>`).join('')}</tbody></table></div>` : '<p style="margin:var(--sp-3) 0 0;color:var(--muted);font-size:var(--fs-2);">Run the same question set, providers, models, and sampling modes in a later period to unlock comparable deltas.</p>'}
        </div>

        ${sampleEstimate?.estimate ? `<div class="card" style="padding:var(--sp-4);border-color:var(--line);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><strong style="display:block;margin-bottom:4px;">${t('engines.next_sample_estimate', {}, 'Next sample estimate')}</strong><span style="font-size:var(--fs-2);color:var(--muted);">${Number(sampleEstimate.estimate.calls || 0)} calls · about ${Number(sampleEstimate.estimate.minutes || 0)} minutes · question set ${escapeHtml(sampleEstimate.question_set_version || 'current')}</span></div>
            <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;"><span class="tag tag-neutral">BYOK ${Number(sampleEstimate.estimate.byok_calls || 0)}</span><span class="tag tag-neutral">Pool ${Number(sampleEstimate.estimate.platform_pool_calls || 0)}</span>${sampleEstimate.estimate.platform_pool_cost_cny_fen ? `<span class="tag tag-warn">Pool cost ¥${(Number(sampleEstimate.estimate.platform_pool_cost_cny_fen) / 100).toFixed(2)}</span>` : ''}</div>
          </div>
          <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-top:var(--sp-3);">${(sampleEstimate.platforms || []).map((item) => `<span class="tag tag-dim">${escapeHtml(item.provider_name || item.engine_name || item.engine_code)}${item.model_id ? ` · ${escapeHtml(item.model_id)}` : ''} · ${escapeHtml(item.funding_source || item.source || 'unavailable')}</span>`).join('')}</div>
        </div>` : ''}

        ${modeGroups.map((group) => `
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${group.title}</h3>
            <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${group.hint}</p>
          </div>
          ${grouped[group.key].length
            ? renderEngineTable(grouped[group.key])
            : `<div style="padding:var(--sp-6);color:var(--muted);font-size:var(--fs-2);">No ${group.title} observations yet.</div>`}
        </div>`).join('')}
        ${grouped.other.length ? `<div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">Other</h3>
          </div>
          ${renderEngineTable(grouped.other)}
        </div>` : ''}

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
                      ? `<span class="tag pill-good">Mentioned${matchedIdentity ? ` via "${escapeHtml(matchedIdentity)}"` : ''}</span>`
                      : '<span class="tag tag-dim">${t('common.not_mentioned', {}, 'Not Mentioned')}</span>';
                    return `
                <div class="sample-replay-card">
                  <div class="sample-head">
                    <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;min-width:0;">
                      <strong class="sample-model-tag">${escapeHtml(s.platform_name || s.platform || 'AI Model')}</strong>
                      ${samplingModeBadge(s.sample_mode === 'manual' || s.terminal === 'web' ? 'Manual - Product interface' : (s.search_enabled ? 'API - Search grounded' : 'API - Parametric knowledge'))}
                      ${mentionBadge}
                    </div>
                    <span style="font-family:var(--font-mono);font-size:11px;color:var(--muted);">${escapeHtml(s.date || '')}</span>
                  </div>

                  <div class="sample-query">${escapeHtml(s.question || 'Question unavailable')}</div>
                  <div class="sample-answer">${escapeHtml(s.ok ? (s.answer || 'Empty model response') : `Sampling failed: ${s.error || 'Unknown provider error'}`)}</div>

                  ${
                    s.citations && s.citations.length
                      ? `
                    <div class="sample-citations">
                      <span style="color:var(--muted);font-weight:600;">${t('engines.citations_label', {}, 'Citations:')}</span>
                      ${s.citations
                        .map(
                          (c) => {
                            const url = String(typeof c === 'string' ? c : c.url || '');
                            return `
                        <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="tag tag-neutral num" style="text-decoration:none;">
                          ${escapeHtml(url.replace(/^https?:\/\//, '').slice(0, 32))}...
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

    document.getElementById('btn-import-surface')?.addEventListener('click', async () => {
      const questions = await workspace.getQuestions(projectId).catch(() => []);
      const options = (questions || []).map((q) => `<option value="${escapeHtml(q.id || '')}">${escapeHtml(q.id || '')} · ${escapeHtml(q.text || '')}</option>`).join('');
      openModal({
        title: 'Log a product-surface answer',
        content: `<p style="margin:0 0 var(--sp-3);color:var(--muted);font-size:var(--fs-2);">Paste what you saw in ChatGPT, Claude.ai, or Google AI Overviews. This stays in a separate cohort from API samples.</p>
          <div class="field"><label>Product surface</label>
            <select id="surface-platform" class="input">
              <option value="chatgpt">ChatGPT Search</option>
              <option value="claude_web">Claude.ai</option>
              <option value="google_ai_overview">Google AI Overviews</option>
              <option value="google_ai_mode">Google AI Mode</option>
              <option value="copilot">Microsoft Copilot</option>
              <option value="gemini_web">Gemini Web</option>
              <option value="meta_ai">Meta AI</option>
              <option value="you_com">You.com</option>
              <option value="mistral_le_chat">Mistral Le Chat</option>
              <option value="nano_ai">Nano AI Search (360)</option>
              <option value="baidu">Baidu AI Search</option>
              <option value="doubao_app">Doubao App / Web</option>
            </select>
          </div>
          <div class="field"><label>Question</label>
            <select id="surface-question" class="input">${options || '<option value="">No questions yet</option>'}</select>
          </div>
          <div class="field"><label>Answer transcript</label>
            <textarea id="surface-answer" class="input" rows="8" placeholder="Paste the exact answer text"></textarea>
          </div>`,
        confirmText: 'Save transcript',
        onConfirm: async () => {
          const platform = document.getElementById('surface-platform')?.value;
          const questionId = document.getElementById('surface-question')?.value;
          const answer = document.getElementById('surface-answer')?.value || '';
          if (!questionId || !answer.trim()) {
            toast.error('Choose a question and paste the answer');
            return false;
          }
          try {
            await workspace.importProductSurface(projectId, {
              platform,
              items: [{ question_id: questionId, answer: answer.trim() }],
            });
            toast.success('Product-surface answer saved');
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

    const gapBtn = document.getElementById('btn-fill-question-gaps');
    if (gapBtn) {
      gapBtn.addEventListener('click', async () => {
        gapBtn.disabled = true;
        try {
          const res = await projects.triggerSampleGaps(projectId);
          if (res?.status === 'no_gaps') {
            toast.success('No question-level sampling gaps remain');
          } else {
            toast.success('Question-level gap sampling queued');
            ctx.pollActiveJobs();
            if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'sample');
          }
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Question gap sampling failed to start'));
        } finally {
          gapBtn.disabled = false;
        }
      });
    }
  },
};
