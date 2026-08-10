/**
 * Toast 提示组件
 */

let toastStack = null;

function getRoot() {
  if (!toastStack) {
    toastStack = document.getElementById('toast-root');
    if (!toastStack) {
      toastStack = document.createElement('div');
      toastStack.id = 'toast-root';
      toastStack.className = 'toast-stack';
      document.body.appendChild(toastStack);
    }
  }
  return toastStack;
}

export function showToast(message, type = 'info', duration = 3500) {
  const root = getRoot();
  const el = document.createElement('div');
  el.className = `toast ${type === 'error' ? 'err' : type === 'success' ? 'good' : ''}`;
  el.textContent = message;
  root.appendChild(el);

  const timer = setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    el.style.transition = 'opacity 180ms ease, transform 180ms ease';
    setTimeout(() => {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 200);
  }, duration);

  el.addEventListener('click', () => {
    clearTimeout(timer);
    if (el.parentNode) el.parentNode.removeChild(el);
  });
}

export const toast = {
  info: (msg, dur) => showToast(msg, 'info', dur),
  success: (msg, dur) => showToast(msg, 'success', dur),
  error: (msg, dur) => showToast(msg, 'error', dur),
  warn: (msg, dur) => showToast(msg, 'warn', dur),
};

export default toast;
