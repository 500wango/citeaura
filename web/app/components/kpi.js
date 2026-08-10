/**
 * KPI 卡片组件
 */

export function renderKpis(kpiList = []) {
  if (!kpiList.length) return '';
  return `
    <div class="kpis">
      ${kpiList
        .map(
          (k) => `
        <div class="kpi">
          <div class="kpi-label">${k.label || ''}</div>
          <div class="kpi-value ${k.className || ''}">${k.value !== undefined ? k.value : '—'}</div>
          ${k.sub ? `<div class="kpi-sub">${k.sub}</div>` : ''}
        </div>
      `
        )
        .join('')}
    </div>
  `;
}

export default { renderKpis };
