/**
 * 
 */

export function renderTabs({ tabs = [], activeId = '', containerClass = '' } = {}) {
  return `
    <div class="tabs ${containerClass}">
      ${tabs
        .map(
          (tab) => `
        <button type="button" class="tab ${tab.id === activeId ? 'on' : ''}" data-tab-id="${tab.id}">
          <span>${tab.label}</span>
          ${tab.count !== undefined ? `<span class="cnt">${tab.count}</span>` : ''}
        </button>
      `
        )
        .join('')}
    </div>
  `;
}

export function bindTabs(rootElement, onTabChange) {
  if (!rootElement) return;
  const buttons = rootElement.querySelectorAll('.tab[data-tab-id]');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tabId = btn.getAttribute('data-tab-id');
      buttons.forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      if (onTabChange) onTabChange(tabId);
    });
  });
}

export default { renderTabs, bindTabs };
