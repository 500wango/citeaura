/**
 * 注册视图
 */

import { auth } from '../api.js';
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
            <h1 class="auth-title">${t('auth.register_title', {}, 'Start 14-Day Free Trial')}</h1>
            <p class="auth-subtitle">${t('auth.register_subtitle', {}, 'No credit card required. Includes 3 projects and full engineering tickets.')}</p>
          </div>

          <form id="register-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <div class="field" style="margin:0;">
              <label for="reg-tenant">${t('auth.tenant_name', {}, 'Organization / Team Name')}</label>
              <input type="text" id="reg-tenant" class="input" placeholder="Acme Growth Inc" required autocomplete="organization">
            </div>

            <div class="field" style="margin:0;">
              <label for="reg-email">${t('auth.email', {}, 'Work Email')}</label>
              <input type="email" id="reg-email" class="input" placeholder="name@company.com" required autocomplete="email">
            </div>

            <div class="field" style="margin:0;">
              <label for="reg-password">${t('auth.password', {}, 'Password')}</label>
              <input type="password" id="reg-password" class="input" placeholder="Minimum 8 characters" minlength="8" required autocomplete="new-password">
            </div>

            <div class="field" style="margin:0;">
              <label for="reg-confirm">${t('auth.confirm_password', {}, 'Confirm Password')}</label>
              <input type="password" id="reg-confirm" class="input" placeholder="Re-enter password" minlength="8" required autocomplete="new-password">
            </div>

            <button type="submit" class="btn btn-primary btn-block" style="margin-top:var(--sp-2);">
              <span>${t('auth.register_btn', {}, 'Create Workspace')}</span>
            </button>
          </form>

          <div class="auth-footer">
            <span>${t('auth.have_account', {}, 'Already have an account?')}</span>
            <a href="#/login" style="font-weight:600;margin-left:var(--sp-1);">${t('auth.sign_in_link', {}, 'Sign In')}</a>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const form = document.getElementById('register-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const tenant_name = document.getElementById('reg-tenant').value.trim();
      const email = document.getElementById('reg-email').value.trim();
      const password = document.getElementById('reg-password').value;
      const confirm = document.getElementById('reg-confirm').value;
      const submitBtn = form.querySelector('button[type="submit"]');

      if (password !== confirm) {
        toast.error(t('auth.passwords_must_match', {}, 'Passwords do not match'));
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.creating', {}, 'Creating...')}`;

      try {
        await auth.register({ tenant_name, email, password });
        toast.success(t('auth.register_success', {}, 'Workspace created successfully'));
        await ctx.reloadSession();
        ctx.navigate('#/onboarding');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Registration failed'));
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.register_btn', {}, 'Create Workspace')}</span>`;
      }
    });
  },
};
