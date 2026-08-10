/**
 * 空状态组件
 * 规则：空状态必须教用户下一步
 */

export function renderEmpty({
  title = 'No data available',
  description = 'Complete the previous step to populate this view with data.',
  actionText = '',
  actionRoute = '',
  onAction = null,
  icon = '',
} = {}) {
  const btnId = `empty-btn-${Math.random().toString(36).slice(2, 8)}`;
  setTimeout(() => {
    const btn = document.getElementById(btnId);
    if (btn && onAction) {
      btn.addEventListener('click', onAction);
    }
  }, 0);

  return `
    <div class="empty">
      ${icon ? `<div style="font-size:32px;margin-bottom:var(--sp-2);">${icon}</div>` : ''}
      <strong>${title}</strong>
      <p style="max-width:44ch;margin:0 auto;color:var(--muted);">${description}</p>
      ${
        actionText
          ? actionRoute
            ? `<a class="btn btn-primary btn-sm" href="#/${actionRoute}">${actionText}</a>`
            : `<button type="button" id="${btnId}" class="btn btn-primary btn-sm">${actionText}</button>`
          : ''
      }
    </div>
  `;
}

export default { renderEmpty };
