/**
 * Traceable sample evidence drawer.
 *
 * Renders only fields returned by the sample replay endpoint. Missing runtime
 * metadata stays absent instead of being filled with inferred values.
 */

import { t } from '../i18n.js';
import { escapeHtml, safeHttpUrl } from '../safe-html.js';
import { openModal } from './modal.js';
import { samplingModeBadge } from './badge.js';

let activeDrawer = null;

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : '';
}

function sampleMode(sample) {
  return sample.sampling_mode_code
    || (sample.sample_mode === 'manual' || sample.terminal === 'web'
      ? 'manual'
      : (sample.search_enabled ? 'search' : 'parametric'));
}

function citationList(sample, mode) {
  const citations = Array.isArray(sample.citations) ? sample.citations : [];
  const safe = citations
    .map((citation) => {
      const raw = typeof citation === 'string' ? citation : citation?.url;
      const url = safeHttpUrl(raw);
      return url ? { url, title: typeof citation === 'object' ? citation?.title || '' : '' } : null;
    })
    .filter(Boolean);

  if (!safe.length) {
    return `<p class="evidence-empty">${escapeHtml(
      mode === 'search'
        ? t('evidence.no_citations', {}, 'No citation URLs were returned for this sample.')
        : t('engines.no_source_urls', {}, 'No source URLs for this mode'),
    )}</p>`;
  }

  return `<ul class="evidence-citations">${safe.map((item) => `
    <li>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || item.url)}</a>
      ${item.title ? `<span>${escapeHtml(item.url)}</span>` : ''}
    </li>`).join('')}</ul>`;
}

function metadataRows(sample) {
  const analysis = sample.analysis && typeof sample.analysis === 'object' ? sample.analysis : {};
  const rows = [
    [t('evidence.run_id', {}, 'Run ID'), sample.run_id],
    [t('evidence.question_id', {}, 'Question ID'), sample.question_id],
    [t('evidence.model', {}, 'Model'), sample.raw_model],
    [t('evidence.market', {}, 'Market'), sample.market],
    [t('evidence.round', {}, 'Round'), sample.round],
    [t('evidence.request_id', {}, 'Request ID'), sample.request_id],
    [t('evidence.elapsed', {}, 'Elapsed'), Number.isFinite(Number(sample.elapsed_ms)) ? `${formatNumber(sample.elapsed_ms)} ms` : ''],
    [t('evidence.retries', {}, 'Retries'), sample.retry_count],
    [t('evidence.search_evidence', {}, 'Search evidence'), sample.search_enabled === true ? t('common.yes', {}, 'Yes') : sample.search_enabled === false ? t('common.no', {}, 'No') : ''],
    [t('evidence.brand_in_question', {}, 'Brand in question'), sample.brand_in_question === true ? t('common.yes', {}, 'Yes') : sample.brand_in_question === false ? t('common.no', {}, 'No') : ''],
    [t('evidence.matched_identity', {}, 'Matched identity'), analysis.matched_identity?.text || analysis.matched_identity?.value],
    [t('evidence.usage', {}, 'Token usage'), sample.usage && typeof sample.usage === 'object' ? JSON.stringify(sample.usage) : sample.usage],
  ];
  return rows
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>`)
    .join('');
}

export function openEvidenceDrawer(sample = {}) {
  if (!sample || typeof sample !== 'object') return null;
  activeDrawer?.close?.();

  const mode = sampleMode(sample);
  const platform = sample.platform_name || sample.platform || t('evidence.unknown_model', {}, 'Model not recorded');
  const timestamp = sample.ts || sample.date || '';
  const answer = sample.ok === false
    ? t('evidence.sample_failed', { error: sample.error || t('evidence.unknown_error', {}, 'Unknown provider error') }, `Sampling failed: ${sample.error || 'Unknown provider error'}`)
    : (sample.answer || t('evidence.empty_answer', {}, 'Empty model response'));

  const content = `
    <div class="evidence-meta">
      <div class="evidence-badges">
        <strong>${escapeHtml(platform)}</strong>
        ${samplingModeBadge(mode)}
        <span class="tag ${sample.ok === false ? 'pill-bad' : 'tag-dim'}">${escapeHtml(sample.ok === false ? t('evidence.failed', {}, 'Failed') : t('evidence.captured', {}, 'Captured'))}</span>
      </div>
      ${timestamp ? `<time class="num">${escapeHtml(timestamp)}</time>` : ''}
    </div>
    <section class="evidence-section">
      <h4>${t('evidence.prompt', {}, 'Prompt')}</h4>
      <p class="evidence-prompt">${escapeHtml(sample.question || t('evidence.question_missing', {}, 'Question text was not stored for this sample.'))}</p>
    </section>
    <section class="evidence-section">
      <h4>${t('evidence.answer', {}, 'Raw answer')}</h4>
      <pre class="evidence-answer">${escapeHtml(answer)}</pre>
    </section>
    <section class="evidence-section">
      <h4>${t('engines.citations_label', {}, 'Citations:')}</h4>
      ${citationList(sample, mode)}
    </section>
    <section class="evidence-section">
      <h4>${t('evidence.runtime', {}, 'Sample provenance')}</h4>
      <dl class="evidence-runtime">${metadataRows(sample)}</dl>
    </section>
  `;

  const modal = openModal({
    title: t('evidence.title', {}, 'Sample evidence'),
    content,
    width: 'min(540px, 100vw)',
    panelClass: 'evidence-panel',
    drawer: true,
    showFooter: false,
    onClose: () => {
      if (activeDrawer === modal) activeDrawer = null;
    },
  });
  activeDrawer = modal;
  return modal;
}

export function closeEvidenceDrawer() {
  activeDrawer?.close?.();
  activeDrawer = null;
}

export default { open: openEvidenceDrawer, close: closeEvidenceDrawer };
