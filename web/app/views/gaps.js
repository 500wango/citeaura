import { projects } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';
import { samplingModeBadge } from '../components/badge.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const framing = await projects.getFraming(projectId).catch(() => null);
    const terms = framing?.terms || [];
    const status = framing
      ? (terms.length ? 'ready' : framing.status === 'ready' ? 'no_descriptors' : framing.status || 'no_descriptors')
      : 'unavailable';
    const emptyStates = {
      no_samples: {
        title: t('gaps.status_no_samples_title', {}, 'No samples recorded'),
        description: t('gaps.status_no_samples_desc', {}, 'Run a labeled sample before reviewing model descriptors. No percentage is inferred from missing data.'),
      },
      brand_not_mentioned: {
        title: t('gaps.status_brand_not_mentioned_title', {}, 'Brand not mentioned in the latest sample'),
        description: t('gaps.status_brand_not_mentioned_desc', {}, 'The latest sample contains no qualifying answers that name the brand, so descriptors are Unmeasured.'),
      },
      no_descriptors: {
        title: t('gaps.status_no_descriptors_title', {}, 'No descriptor phrases detected'),
        description: t('gaps.status_no_descriptors_desc', {}, 'The latest sample mentions the brand, but no recurring descriptor phrase passed extraction.'),
      },
      unavailable: {
        title: t('gaps.status_unavailable_title', {}, 'Framing data unavailable'),
        description: t('gaps.status_unavailable_desc', {}, 'The latest framing result could not be loaded. Refresh the page or run sampling again.'),
      },
    };
    const emptyState = emptyStates[status] || emptyStates.unavailable;
    const sampledAt = framing?.date
      ? t('gaps.sampled_at', { date: framing.date }, `Latest sample: ${framing.date}`)
      : '';
    const shareNote = framing
      ? t('gaps.share_note', { mentions: framing.mentioned_samples || 0 }, `Share is calculated within ${framing.mentioned_samples || 0} answers that mentioned the brand in this sample.`)
      : '';

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('gaps.title', {}, 'How models describe you')}</h1>
            <p class="view-desc">${t('gaps.desc', {}, 'Review the recurring descriptors that appear in recorded model answers. This view reflects sampled phrasing only. It does not infer factual correctness.')}</p>
          </div>
        </div>
        ${terms.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div class="gaps-card-head">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('gaps.observed_title', {}, 'Observed descriptors')}</h3>
              <span class="gaps-meta">${t('gaps.sample_stats', { samples: framing.sample_count || 0, mentions: framing.mentioned_samples || 0 }, `${framing.sample_count || 0} samples, ${framing.mentioned_samples || 0} mentions`)}${sampledAt ? ` · ${escapeHtml(sampledAt)}` : ''}</span>
            </div>
            <p class="gaps-share-note">${escapeHtml(shareNote)}</p>
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead><tr><th>${t('gaps.col_descriptor', {}, 'Descriptor')}</th><th style="text-align:right;">${t('gaps.col_share', {}, 'Share')}</th><th>${t('gaps.col_evidence', {}, 'Evidence')}</th></tr></thead>
                <tbody>
                  ${terms.map((term) => {
                    const numericShare = Number(term.share);
                    const share = term.share === null || term.share === undefined || !Number.isFinite(numericShare)
                      ? t('common.unmeasured', {}, 'Unmeasured')
                      : `${(numericShare * 100).toFixed(1)}%`;
                    const evidence = (term.evidence || []).map((item) => `
                      <div class="gaps-evidence-item">
                        <div class="gaps-evidence-meta">
                          <span>${escapeHtml(item.platform_name || item.platform || '')}</span>
                          ${samplingModeBadge(item.sampling_mode)}
                        </div>
                        <blockquote>${escapeHtml(item.excerpt || '')}</blockquote>
                        ${item.question ? `<div class="gaps-evidence-question"><span>${t('gaps.evidence_question', {}, 'Question')}:</span> ${escapeHtml(item.question)}</div>` : ''}
                      </div>
                    `).join('');
                    const countLabel = t('gaps.term_mentions', { count: term.count ?? '—' }, `${term.count ?? '—'} mentions`);
                    return `<tr><td><strong>${escapeHtml(term.term)}</strong><div class="gaps-term-count">${escapeHtml(countLabel)}</div></td><td data-num class="num">${share}</td><td>${evidence || '—'}</td></tr>`;
                  }).join('')}
                </tbody>
              </table>
            </div>
          </div>` : renderEmpty(emptyState)}
      </div>`;
  },
};
