/**
 * 
 * ：
 */

export function renderEmpty({
  title = 'No data available',
  description = 'Complete the previous step to populate this view with data.',
  actionText = '',
  actionRoute = '',
  onAction = null,
  icon = '',
} = {}) {
  return `
    <div class="empty">
      ${icon ? `<div style="font-size:32px;margin-bottom:var(--sp-2);">${icon}</div>` : ''}
      <strong>${title}</strong>
      <p style="max-width:44ch;margin:0 auto;color:var(--muted);">${description}</p>
      ${
        actionText
          ? actionRoute
            ? `<a class="btn btn-primary btn-sm" href="#/${actionRoute}">${actionText}</a>`
            : `<button type="button" class="btn btn-primary btn-sm" data-empty-action="true">${actionText}</button>`
          : ''
      }
    </div>
  `;
}

export function bindEmptyAction(root, onAction) {
  if (!root || typeof onAction !== 'function') return;
  root.querySelector('[data-empty-action]')?.addEventListener('click', onAction);
}

export default { renderEmpty };
