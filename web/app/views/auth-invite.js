/**
 * 
 */

import { auth } from '../api.js?v=3.4';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    const token = ctx.params.token || new URLSearchParams(location.search).get('token') || '';
    let preview = null;
    let loadError = null;

    if (token) {
      try {
        preview = await auth.getInvitationPreview(token);
      } catch (err) {
        loadError = err.detail || err.error || 'Invitation is invalid or has expired';
      }
    }

    if (!token || loadError) {
      return `
        <div class="auth-wrapper">
          <div class="auth-box">
            <div class="auth-header">
              <a class="brand" href="/">
                <span class="brand-mark" style="width:32px;height:32px;"></span>
                <span class="brand-word" style="font-size:var(--fs-6);">CiteAura</span>
              </a>
              <h1 class="auth-title" style="color:var(--bad);">${t('auth.invalid_invite_title', {}, 'Invalid Invitation')}</h1>
              <p class="auth-subtitle">${loadError || t('auth.invalid_invite_desc', {}, 'This invitation link is missing or no longer valid.')}</p>
            </div>
            <div class="auth-footer">
              <a href="#/login" class="btn btn-secondary btn-block">${t('auth.back_to_login', {}, 'Back to Sign In')}</a>
            </div>
          </div>
        </div>
      `;
    }

    return `
      <div class="auth-wrapper">
        <div class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark" style="width:32px;height:32px;"></span>
              <span class="brand-word" style="font-size:var(--fs-6);">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.join_team_title', {}, 'Join Team Workspace')}</h1>
            <p class="auth-subtitle">
              ${t('auth.invited_to_join', { tenant: preview.tenant?.name || 'Organization', role: preview.role || 'Member' }, `You have been invited to join ${preview.tenant?.name || 'Organization'} as ${preview.role || 'Member'}.`)}
            </p>
          </div>

          <form id="invite-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <input type="hidden" id="invite-token" value="${token}">

            <div class="field" style="margin:0;">
              <label>${t('auth.email', {}, 'Email')}</label>
              <input type="email" id="invite-email" class="input" value="${preview.email || ''}" disabled>
            </div>

            <div class="field" style="margin:0;">
              <label for="invite-password">${t('auth.password', {}, 'Password')}</label>
              <input type="password" id="invite-password" class="input" placeholder="Set account password" minlength="8" required autocomplete="new-password">
            </div>

            <button type="submit" class="btn btn-primary btn-block" style="margin-top:var(--sp-2);">
              <span>${t('auth.accept_invite_btn', {}, 'Accept Invitation & Join')}</span>
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
    const form = document.getElementById('invite-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const token = document.getElementById('invite-token').value;
      const email = document.getElementById('invite-email').value;
      const password = document.getElementById('invite-password').value;
      const submitBtn = form.querySelector('button[type="submit"]');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.joining', {}, 'Joining...')}`;

      try {
        let registered = false;
        try {
          await auth.login({ email, password });
        } catch (loginError) {
          if (loginError.status !== 401) throw loginError;
          try {
            await auth.register({ email, password, invitation_token: token });
            registered = true;
            await auth.login({ email, password });
          } catch (registerError) {
            throw registerError;
          }
        }
        if (!registered) await auth.acceptInvitation({ token });
        toast.success(t('auth.invite_accepted', {}, 'Invitation accepted! Welcome to the team.'));
        await ctx.reloadSession();
        ctx.navigate('#/overview');
      } catch (err) {
        toast.error(tError(err));
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.accept_invite_btn', {}, 'Accept Invitation & Join')}</span>`;
      }
    });
  },
};
