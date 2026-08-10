/**
 * 骨架屏加载组件
 */

export function renderSkeleton({ rows = 4, height = 40 } = {}) {
  let html = '<div style="display:flex;flex-direction:column;gap:var(--sp-3);width:100%;">';
  for (let i = 0; i < rows; i++) {
    html += `<div class="skeleton" style="height:${height}px;width:100%;"></div>`;
  }
  html += '</div>';
  return html;
}

export default { renderSkeleton };
