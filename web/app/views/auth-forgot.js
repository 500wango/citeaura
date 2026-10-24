/**
 * 
 */

import { auth } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: (ctx) => {
    return `
      <div class="auth-wrapper">
        <main class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark auth-brand-mark"></span>
              <span class="brand-word auth-brand-word">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.forgot_title', {}, 'Reset Password')}</h1>
            <p class="auth-subtitle">${t('auth.forgot_subtitle', {}, 'Enter your registered work email. If an account exists, a reset link will be dispatched.')}</p>
          </div>

          <form id="forgot-form" class="auth-form">
            <div class="field">
              <label for="forgot-email">${t('auth.email', {}, 'Work Email')}</label>
              <input type="email" id="forgot-email" class="input" placeholder="name@company.com" required autocomplete="email">
            </div>

            <p id="forgot-status" class="form-status is-error" role="alert" aria-live="polite" hidden></p>

            <button type="submit" class="btn btn-primary btn-block">
              <span>${t('auth.send_reset_link', {}, 'Send Reset Link')}</span>
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
    const form = document.getElementById('forgot-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('forgot-email').value.trim();
      const submitBtn = form.querySelector('button[type="submit"]');
      const status = document.getElementById('forgot-status');

      status.hidden = true;
      status.textContent = '';
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.submitting', {}, 'Sending...')}`;

      try {
        await auth.forgotPassword({ email });
        toast.success(t('auth.reset_email_sent', {}, 'Password reset instructions sent. Please check your inbox.'));
        ctx.navigate('#/login');
      } catch (err) {
        const message = tError(err);
        status.textContent = message;
        status.hidden = false;
        toast.error(message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.send_reset_link', {}, 'Send Reset Link')}</span>`;
      }
    });
  },
};
