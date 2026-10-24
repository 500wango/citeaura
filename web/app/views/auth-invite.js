/**
 * 
 */

import { auth } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const token = ctx.params.token || new URLSearchParams(location.search).get('token') || '';
    let preview = null;
    let loadError = null;

    if (token) {
      try {
        preview = await auth.getInvitationPreview(token);
      } catch (err) {
        loadError = tError(err, 'auth.invalid_invite_desc');
      }
    }
    if (token && !preview && !loadError) {
      loadError = t('auth.invalid_invite_desc', {}, 'This invitation link is missing or no longer valid.');
    }

    if (!token || loadError) {
      return `
        <div class="auth-wrapper">
          <main class="auth-box">
            <div class="auth-header">
              <a class="brand" href="/">
                <span class="brand-mark auth-brand-mark"></span>
                <span class="brand-word auth-brand-word">CiteAura</span>
              </a>
              <h1 class="auth-title auth-title-error">${t('auth.invalid_invite_title', {}, 'Invalid Invitation')}</h1>
              <p class="auth-subtitle" role="alert">${escapeHtml(loadError || t('auth.invalid_invite_desc', {}, 'This invitation link is missing or no longer valid.'))}</p>
            </div>
            <div class="auth-footer">
              <a href="#/login" class="btn btn-secondary btn-block">${t('auth.back_to_login', {}, 'Back to Sign In')}</a>
            </div>
          </main>
        </div>
      `;
    }

    return `
      <div class="auth-wrapper">
        <main class="auth-box">
          <div class="auth-header">
            <a class="brand" href="/">
              <span class="brand-mark auth-brand-mark"></span>
              <span class="brand-word auth-brand-word">CiteAura</span>
            </a>
            <h1 class="auth-title">${t('auth.join_team_title', {}, 'Join Team Workspace')}</h1>
            <p class="auth-subtitle">
              ${t('auth.invited_to_join', { tenant: escapeHtml(preview.tenant?.name || t('auth.organization', {}, 'Organization')), role: escapeHtml(preview.role || t('auth.member', {}, 'Member')) }, `You have been invited to join ${escapeHtml(preview.tenant?.name || 'Organization')} as ${escapeHtml(preview.role || 'Member')}.`)}
            </p>
          </div>

          <form id="invite-form" class="auth-form">
            <input type="hidden" id="invite-token" value="${escapeHtml(token)}">

            <div class="field">
              <label for="invite-email">${t('auth.email', {}, 'Email')}</label>
              <input type="email" id="invite-email" class="input" value="${escapeHtml(preview.email || '')}" disabled aria-describedby="invite-email-hint">
              <div id="invite-email-hint" class="field-hint">${t('auth.invite_email_locked', {}, 'This invitation is tied to the email address above.')}</div>
            </div>

            <div class="field">
              <label for="invite-password">${t('auth.password', {}, 'Password')}</label>
              <input type="password" id="invite-password" class="input" placeholder="Set account password" minlength="8" required autocomplete="new-password">
              <div class="field-hint">${t('auth.password_min_hint', {}, 'Minimum 8 characters.')}</div>
            </div>

            <p id="invite-status" class="form-status is-error" role="alert" aria-live="polite" hidden></p>

            <button type="submit" class="btn btn-primary btn-block">
              <span>${t('auth.accept_invite_btn', {}, 'Accept Invitation & Join')}</span>
            </button>
          </form>

          <div class="auth-footer">
            <span>${t('auth.have_account', {}, 'Already have an account?')}</span>
            <a href="#/login" class="auth-footer-link">${t('auth.sign_in_link', {}, 'Sign In')}</a>
          </div>
        </main>
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
      const status = document.getElementById('invite-status');

      status.hidden = true;
      status.textContent = '';
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
        const message = tError(err);
        status.textContent = message;
        status.hidden = false;
        toast.error(message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('auth.accept_invite_btn', {}, 'Accept Invitation & Join')}</span>`;
      }
    });
  },
};
