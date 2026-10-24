/**
 * Badge and Status Pill Component
 * Supports sampling modes and A/B/C/D letter grades
 */

import { t } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';

export function samplingModeLabel(mode) {
  const norm = String(mode || '').toLowerCase();
  if (
    norm === 'parametric'
    || norm.includes('parametric')
    || norm.includes('model knowledge')
    || norm.includes('\u53c2\u6570')
  ) {
    return t('landing.mode_parametric', {}, 'API · Model knowledge');
  }
  if (
    norm === 'search'
    || norm.includes('search')
    || norm.includes('grounded')
    || norm.includes('retrieval')
    || norm.includes('\u8054\u7f51')
  ) {
    return t('landing.mode_search', {}, 'API · Web-grounded retrieval');
  }
  if (
    norm === 'manual'
    || norm.includes('manual')
    || norm.includes('surface')
    || norm.includes('human')
    || norm.includes('\u4eba\u5de5')
    || norm.includes('\u4ea7\u54c1\u7aef')
  ) {
    return t('landing.mode_manual', {}, 'Manual · Product surface');
  }
  return t('common.unmeasured', {}, 'Unmeasured');
}

export function samplingModeBadge(mode) {
  const norm = String(mode || '').toLowerCase();
  let cssClass = 'mode-unmeasured';
  if (norm.includes('parametric') || norm.includes('model knowledge') || norm.includes('\u53c2\u6570')) cssClass = 'mode-parametric';
  else if (norm.includes('search') || norm.includes('grounded') || norm.includes('retrieval') || norm.includes('\u8054\u7f51')) cssClass = 'mode-search';
  else if (norm.includes('manual') || norm.includes('surface') || norm.includes('human') || norm.includes('\u4eba\u5de5') || norm.includes('\u4ea7\u54c1\u7aef')) cssClass = 'mode-manual';
  return `<span class="mode-badge ${cssClass}">${samplingModeLabel(mode)}</span>`;
}

export function gradeBadge(grade) {
  const g = ['A', 'B', 'C', 'D'].includes(String(grade || '').toUpperCase())
    ? String(grade).toUpperCase()
    : 'D';
  return `<span class="grade-badge grade-${g}">${g}</span>`;
}

export function statusPill(status, label) {
  const s = String(status || '').toLowerCase();
  let pillClass = 'tag-dim';
  if (s === 'done' || s === 'completed' || s === 'good' || s === 'active') pillClass = 'pill-good';
  else if (s === 'running' || s === 'in_progress' || s === 'queued') pillClass = 'tag-accent';
  else if (s === 'warn' || s === 'warning' || s === 'todo') pillClass = 'pill-warn';
  else if (s === 'failed' || s === 'error' || s === 'bad') pillClass = 'pill-bad';

  const statusKeys = {
    todo: 'plan.status_todo',
    doing: 'plan.status_doing',
    done: 'plan.status_done',
    blocked: 'plan.status_blocked',
    wontfix: 'plan.status_wontfix',
  };
  const resolvedLabel = label || (statusKeys[s] ? t(statusKeys[s], {}, status) : status);
  return `<span class="tag ${pillClass}">${escapeHtml(resolvedLabel)}</span>`;
}

export default {
  samplingModeLabel,
  samplingModeBadge,
  gradeBadge,
  statusPill,
};
