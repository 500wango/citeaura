/**
 * Badge and Status Pill Component
 * Supports sampling modes and A/B/C/D letter grades
 */

import { t } from '../i18n.js';

export function samplingModeBadge(mode) {
  const norm = String(mode || '').toLowerCase();
  if (
    norm === 'parametric'
    || norm.includes('parametric')
    || norm.includes('model knowledge')
    || norm.includes('\u53c2\u6570')
  ) {
    return `<span class="mode-badge mode-parametric">${t('landing.mode_parametric', {}, 'API · Model knowledge')}</span>`;
  }
  if (
    norm === 'search'
    || norm.includes('search')
    || norm.includes('grounded')
    || norm.includes('retrieval')
    || norm.includes('\u8054\u7f51')
  ) {
    return `<span class="mode-badge mode-search">${t('landing.mode_search', {}, 'API · Web-grounded retrieval')}</span>`;
  }
  if (
    norm === 'manual'
    || norm.includes('manual')
    || norm.includes('surface')
    || norm.includes('human')
    || norm.includes('\u4eba\u5de5')
    || norm.includes('\u4ea7\u54c1\u7aef')
  ) {
    return `<span class="mode-badge mode-manual">${t('landing.mode_manual', {}, 'Manual · Product surface')}</span>`;
  }
  return `<span class="mode-badge mode-unmeasured">${t('common.unmeasured', {}, 'Unmeasured')}</span>`;
}

export function gradeBadge(grade) {
  const g = (grade || 'D').toUpperCase();
  return `<span class="grade-badge grade-${g}">${g}</span>`;
}

export function statusPill(status, label) {
  const s = String(status || '').toLowerCase();
  let pillClass = 'tag-dim';
  if (s === 'done' || s === 'completed' || s === 'good' || s === 'active') pillClass = 'pill-good';
  else if (s === 'running' || s === 'in_progress' || s === 'queued') pillClass = 'tag-accent';
  else if (s === 'warn' || s === 'warning' || s === 'todo') pillClass = 'pill-warn';
  else if (s === 'failed' || s === 'error' || s === 'bad') pillClass = 'pill-bad';

  return `<span class="tag ${pillClass}">${label || status}</span>`;
}

export default {
  samplingModeBadge,
  gradeBadge,
  statusPill,
};
