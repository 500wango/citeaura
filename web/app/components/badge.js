/**
 * 徽章与标签组件
 * 严格支持三采样模式标注（硬约束 #7）与 A/B/C/D 评级
 */

import { t } from '../i18n.js';

export function samplingModeBadge(mode) {
  const norm = String(mode || '').toLowerCase();
  if (norm.includes('parametric') || norm.includes('参数化') || norm.includes('model')) {
    return `<span class="mode-badge mode-parametric">${t('landing.mode_parametric', {}, 'API · Model knowledge')}</span>`;
  }
  if (norm.includes('search') || norm.includes('联网') || norm.includes('grounded')) {
    return `<span class="mode-badge mode-search">${t('landing.mode_search', {}, 'API · Web-grounded retrieval')}</span>`;
  }
  if (norm.includes('manual') || norm.includes('人工') || norm.includes('surface')) {
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
