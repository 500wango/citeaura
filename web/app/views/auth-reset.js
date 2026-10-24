/**
 * 
 */

import { auth } from '../api.js';
import { t, tError } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';

export default {
  render: (ctx) => {
    const token = ctx.params.token || new URLSearchParams(location.search).get('token') || '';
    return `
      <div class="auth-wrapper">
        <main class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark auth-brand-mark"></span>
              <span class="brand-word auth-brand-word">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.set_new_password', {}, 'Set New Password')}</h1>
            <p class="auth-subtitle">${t('auth.set_new_password_subtitle', {}, 'Enter your new account password below.')}</p>
          </div>

          <form id="reset-form" class="auth-form">
            <input type="hidden" id="reset-token" value="${escapeHtml(token)}">

            <div class="field">
              <label for="new-password">${t('auth.new_password', {}, 'New Password')}</label>
              <input type="password" id="new-password" class="input" placeholder="${t('auth.password_min_hint', {}, 'Minimum 8 characters.')}" minlength="8" required autocomplete="new-password">
              <div class="field-hint">${t('auth.password_min_hint', {}, 'Minimum 8 characters.')}</div>
            </div>

            <div class="field">
              <label for="new-password-confirm">${t('auth.confirm_password', {}, 'Confirm New Password')}</label>
              <input type="password" id="new-password-confirm" class="input" placeholder="${t('auth.reenter_new_password', {}, 'Re-enter new password')}" minlength="8" required autocomplete="new-password">
            </div>

            <p id="reset-status" class="form-status is-error" role="alert" aria-live="polite" hidden></p>

            <button type="submit" class="btn btn-primary btn-block">
              <span>${t('auth.update_password_btn', {}, 'Update Password')}</span>
            </button>
          </form>

          <div class="auth-footer">
            <a href="#/login" class="auth-footer-link">← ${t('auth.back_to_login', {}, 'Back to Sign In')}</a>
          </div>
        </main>
      </div>
    `;
  },

  mounted: (ctx) => {
    const form = document.getElementById('reset-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const token = document.getElementById('reset-token').value;
      const password = document.getElementById('new-password').value;
      const confirm = document.getElementById('new-password-confirm').value;
      const submitBtn = form.querySelector('button[type="submit"]');
      const status = document.getElementById('reset-status');

      status.hidden = true;
      status.textContent = '';

      if (!token) {
        const message = t('auth.missing_token', {}, 'Invalid or missing reset token');
        status.textContent = message;
        status.hidden = false;
        toast.error(message);
        return;
      }
      if (password !== confirm) {
        const message = t('auth.passwords_must_match', {}, 'Passwords do not match');
        status.textContent = message;
        status.hidden = false;
        toast.error(message);
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.submitting', {}, 'Updating...')}`;

      try {
        await auth.resetPassword({ token, password });
        toast.success(t('auth.password_reset_success', {}, 'Password updated. Please sign in with your new password.'));
        ctx.navigate('#/login');
      } catch (err) {
        const message = tError(err);
        status.textContent = message;
        status.hidden = false;
        toast.error(message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.update_password_btn', {}, 'Update Password')}</span>`;
      }
    });
  },
};
