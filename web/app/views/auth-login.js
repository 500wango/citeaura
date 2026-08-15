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
            <h1 class="auth-title">${t('auth.login_title', {}, 'Sign In to Workspace')}</h1>
            <p class="auth-subtitle">${t('auth.login_subtitle', {}, 'Enter your email and password to access your brand measurement projects.')}</p>
          </div>

          <form id="login-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <div class="field" style="margin:0;">
              <label for="login-email">${t('auth.email', {}, 'Work Email')}</label>
              <input type="email" id="login-email" class="input" placeholder="name@company.com" required autocomplete="email">
            </div>

            <div class="field" style="margin:0;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-1);">
                <label for="login-password" style="margin:0;">${t('auth.password', {}, 'Password')}</label>
                <a href="#/forgot-password" style="font-size:var(--fs-1);">${t('auth.forgot_password_link', {}, 'Forgot password?')}</a>
              </div>
              <input type="password" id="login-password" class="input" placeholder="••••••••" required autocomplete="current-password">
            </div>

            <button type="submit" class="btn btn-primary btn-block" style="margin-top:var(--sp-2);">
              <span>${t('auth.login_btn', {}, 'Sign In')}</span>
            </button>
          </form>

          <div class="auth-footer">
            <span>${t('auth.no_account', {}, "Don't have an account?")}</span>
            <a href="#/register" style="font-weight:600;margin-left:var(--sp-1);">${t('auth.start_trial', {}, 'Start 14-day free trial')}</a>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const form = document.getElementById('login-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('login-email').value.trim();
      const password = document.getElementById('login-password').value;
      const submitBtn = form.querySelector('button[type="submit"]');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.signing_in', {}, 'Signing in...')}`;

      try {
        await auth.login({ email, password });
        await ctx.reloadSession();
        toast.success(t('auth.login_success', {}, 'Signed in successfully'));
        // 保留落地页套餐意图（如 ?plan=pro），登录后直接进入升级结账。
        let intentPlan = '';
        try {
          intentPlan = String(sessionStorage.getItem('citeaura_intent_plan') || '').toLowerCase();
        } catch (e) {}
        if (intentPlan && ['starter', 'pro', 'agency', 'enterprise'].includes(intentPlan)) {
          ctx.navigate(`#/billing?plan=${encodeURIComponent(intentPlan)}`);
        } else {
          ctx.navigate('#/overview');
        }
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Incorrect email or password'));
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.login_btn', {}, 'Sign In')}</span>`;
      }
    });
  },
};
