/**
 * Modal 
 */

import { escapeHtml, setSafeHtml } from '../safe-html.js';
import { t } from '../i18n.js';

let modalRoot = null;
let activeCleanup = null;

function getRoot() {
  if (!modalRoot) {
    modalRoot = document.getElementById('modal-root');
    if (!modalRoot) {
      modalRoot = document.createElement('div');
      modalRoot.id = 'modal-root';
      document.body.appendChild(modalRoot);
    }
  }
  return modalRoot;
}

export function openModal({
  title = '',
  content = '',
  width = 'min(580px, 95vw)',
  showFooter = true,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  isDanger = false,
  onConfirm = null,
  onCancel = null,
  onClose = null,
} = {}) {
  closeModal();

  const root = getRoot();
  const backdrop = document.createElement('div');
  backdrop.className = 'modal';
  backdrop.setAttribute('role', 'presentation');

  const box = document.createElement('div');
  box.className = 'box';
  box.style.width = width;
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-labelledby', 'modal-title');

  setSafeHtml(box, `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--sp-4);">
      <h3 id="modal-title" style="font-size:var(--fs-5);font-weight:700;margin:0;">${escapeHtml(title)}</h3>
      <button type="button" class="modal-close-btn" aria-label="${escapeHtml(t('common.close', {}, 'Close dialog'))}" style="color:var(--muted);padding:4px;cursor:pointer;">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="modal-body" style="font-size:var(--fs-3);line-height:1.6;color:var(--ink-2);margin-bottom:var(--sp-6);">
      ${typeof content === 'string' ? content : ''}
    </div>
    ${
      showFooter
        ? `
      <div style="display:flex;align-items:center;justify-content:flex-end;gap:var(--sp-3);padding-top:var(--sp-4);border-top:1px solid var(--line);">
        <button type="button" class="btn btn-secondary btn-cancel">${escapeHtml(cancelText)}</button>
        <button type="button" class="btn ${isDanger ? 'btn-danger' : 'btn-primary'} btn-confirm">${escapeHtml(confirmText)}</button>
      </div>
    `
        : ''
    }
  `);

  if (typeof content !== 'string' && content instanceof HTMLElement) {
    box.querySelector('.modal-body').appendChild(content);
  }

  backdrop.appendChild(box);
  root.appendChild(backdrop);

  const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const cleanup = () => {
    if (activeCleanup === cleanup) activeCleanup = null;
    document.removeEventListener('keydown', handleKeydown);
    if (backdrop.parentNode) {
      backdrop.parentNode.removeChild(backdrop);
    }
    if (onClose) onClose();
    previouslyFocused?.focus?.({ preventScroll: true });
  };
  activeCleanup = cleanup;

  box.querySelector('.modal-close-btn').addEventListener('click', cleanup);

  if (showFooter) {
    box.querySelector('.btn-cancel').addEventListener('click', () => {
      if (onCancel) onCancel();
      cleanup();
    });

    box.querySelector('.btn-confirm').addEventListener('click', async () => {
      if (onConfirm) {
        const result = await onConfirm();
        if (result === false) return; // 
      }
      cleanup();
    });
  }

  // 
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) cleanup();
  });

  // ESC 
  const handleKeydown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      cleanup();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = box.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  document.addEventListener('keydown', handleKeydown);
  queueMicrotask(() => box.querySelector('.modal-close-btn')?.focus?.({ preventScroll: true }));

  return { close: cleanup, box };
}

export function closeModal() {
  if (activeCleanup) {
    activeCleanup();
    return;
  }
  const root = getRoot();
  root.replaceChildren();
}

export function confirmModal(message, options = {}) {
  return new Promise((resolve) => {
    openModal({
      title: options.title || 'Please Confirm',
      content: `<p style="margin:0;">${escapeHtml(message)}</p>`,
      confirmText: options.confirmText || 'Confirm',
      cancelText: options.cancelText || 'Cancel',
      isDanger: options.isDanger || false,
      onConfirm: () => {
        resolve(true);
        return true;
      },
      onCancel: () => {
        resolve(false);
      },
      onClose: () => {
        resolve(false);
      },
    });
  });
}

export default {
  open: openModal,
  close: closeModal,
  confirm: confirmModal,
};
