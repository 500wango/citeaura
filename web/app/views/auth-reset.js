/**
 * 
 */

import { auth } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: (ctx) => {
    const token = ctx.params.token || new URLSearchParams(location.search).get('token') || '';
    return `
      <div class="auth-wrapper">
        <div class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark" style="width:32px;height:32px;"></span>
              <span class="brand-word" style="font-size:var(--fs-6);">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.set_new_password', {}, 'Set New Password')}</h1>
            <p class="auth-subtitle">${t('auth.set_new_password_subtitle', {}, 'Enter your new account password below.')}</p>
          </div>

          <form id="reset-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <input type="hidden" id="reset-token" value="${token}">

            <div class="field" style="margin:0;">
              <label for="new-password">${t('auth.new_password', {}, 'New Password')}</label>
              <input type="password" id="new-password" class="input" placeholder="Minimum 8 characters" minlength="8" required autocomplete="new-password">
            </div>

            <div class="field" style="margin:0;">
              <label for="new-password-confirm">${t('auth.confirm_password', {}, 'Confirm New Password')}</label>
              <input type="password" id="new-password-confirm" class="input" placeholder="Re-enter new password" minlength="8" required autocomplete="new-password">
            </div>

            <button type="submit" class="btn btn-primary btn-block" style="margin-top:var(--sp-2);">
              <span>${t('auth.update_password_btn', {}, 'Update Password')}</span>
            </button>
          </form>

          <div class="auth-footer">
            <a href="#/login" style="font-weight:600;">← ${t('auth.back_to_login', {}, 'Back to Sign In')}</a>
          </div>
        </div>
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

      if (!token) {
        toast.error(t('auth.missing_token', {}, 'Invalid or missing reset token'));
        return;
      }
      if (password !== confirm) {
        toast.error(t('auth.passwords_must_match', {}, 'Passwords do not match'));
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.submitting', {}, 'Updating...')}`;

      try {
        await auth.resetPassword({ token, password });
        toast.success(t('auth.password_reset_success', {}, 'Password updated. Please sign in with your new password.'));
        ctx.navigate('#/login');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Password reset failed or token expired'));
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.update_password_btn', {}, 'Update Password')}</span>`;
      }
    });
  },
};
