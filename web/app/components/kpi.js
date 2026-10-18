/**
 * KPI 
 */

import { escapeHtml } from '../safe-html.js';

export function renderKpis(kpiList = []) {
  if (!kpiList.length) return '';
  return `
    <div class="kpis">
      ${kpiList
        .map(
          (k) => `
        <div class="kpi">
          <div class="kpi-label">${escapeHtml(k.label || '')}</div>
          <div class="kpi-value ${escapeHtml(k.className || '')}">${k.value !== undefined ? k.value : '—'}</div>
          ${k.sub ? `<div class="kpi-sub">${escapeHtml(k.sub)}</div>` : ''}
        </div>
      `
        )
        .join('')}
    </div>
  `;
}

export default { renderKpis };
