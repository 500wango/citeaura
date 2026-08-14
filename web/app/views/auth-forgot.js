/**
 * 
 */

import { auth } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: (ctx) => {
    return `
      <div class="auth-wrapper">
        <div class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark" style="width:32px;height:32px;"></span>
              <span class="brand-word" style="font-size:var(--fs-6);">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.forgot_title', {}, 'Reset Password')}</h1>
            <p class="auth-subtitle">${t('auth.forgot_subtitle', {}, 'Enter your registered work email. If an account exists, a reset link will be dispatched.')}</p>
          </div>

          <form id="forgot-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <div class="field" style="margin:0;">
              <label for="forgot-email">${t('auth.email', {}, 'Work Email')}</label>
              <input type="email" id="forgot-email" class="input" placeholder="name@company.com" required autocomplete="email">
            </div>

            <button type="submit" class="btn btn-primary btn-block" style="margin-top:var(--sp-2);">
              <span>${t('auth.send_reset_link', {}, 'Send Reset Link')}</span>
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
    const form = document.getElementById('forgot-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('forgot-email').value.trim();
      const submitBtn = form.querySelector('button[type="submit"]');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.submitting', {}, 'Sending...')}`;

      try {
        await auth.forgotPassword({ email });
        toast.success(t('auth.reset_email_sent', {}, 'Password reset instructions sent. Please check your inbox.'));
        ctx.navigate('#/login');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to request password reset'));
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.send_reset_link', {}, 'Send Reset Link')}</span>`;
      }
    });
  },
};
