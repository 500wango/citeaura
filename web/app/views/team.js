/**
 *  (Team & Permissions)
 */

import { team } from '../api.js';
import { t, tError } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';

let pendingInviteUrl = '';

export default {
  render: async (ctx) => {
    let members = [];
    let invitations = [];

    try {
      [members, invitations] = await Promise.all([
        team.getMembers().catch(() => []),
        team.getInvitations().catch(() => []),
      ]);
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('team.title', {}, 'Team Members & Permissions')}</h1>
            <p class="view-desc">
              ${t('team.desc', {}, 'Manage organization workspace collaborators. Roles support Owner (full administration), Editor (project execution), and Viewer (read-only).')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-invite-member" class="btn btn-primary btn-sm">
              + ${t('team.invite_btn', {}, 'Invite Team Member')}
            </button>
          </div>
        </div>

        <!-- Active Members List -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('team.members_list', {}, 'Active Members')}</h3>
          </div>

          <div class="tbl" style="overflow-x:auto;">
            <table class="table">
              <thead>
                <tr>
                  <th>${t('team.col_member', {}, 'Member Email')}</th>
                  <th>${t('team.col_role', {}, 'Role')}</th>
                  <th>${t('common.joined', {}, 'Joined Date')}</th>
                  <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                </tr>
              </thead>
              <tbody>
                ${members
                  .map(
                    (m) => `
                  <tr>
                    <td><strong>${escapeHtml(m.email)}</strong></td>
                    <td>
                      <span class="tag ${m.role === 'owner' ? 'tag-accent' : 'tag-neutral'}">
                        ${escapeHtml(m.role || 'editor')}
                      </span>
                    </td>
                    <td class="num">${m.created_at ? new Date(m.created_at).toLocaleDateString() : '—'}</td>
                    <td style="text-align:right;">
                      ${
                        m.role !== 'owner'
                          ? `<button type="button" class="btn btn-ghost btn-sm btn-remove-member" data-id="${m.user_id || m.id}" style="color:var(--bad);">
                              ${t('common.remove', {}, 'Remove')}
                            </button>`
                          : `<span style="font-size:11px;color:var(--muted);">${t('team.workspace_owner', {}, 'Workspace Owner')}</span>`
                      }
                    </td>
                  </tr>
                `
                  )
                  .join('')}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Pending Invitations -->
        ${
          invitations && invitations.length
            ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('team.pending_invitations', {}, 'Pending Invitations')}</h3>
            </div>
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('common.email', {}, 'Email')}</th>
                    <th>${t('common.role', {}, 'Role')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${invitations
                    .map(
                      (inv) => `
                    <tr>
                    <td><strong>${escapeHtml(inv.email)}</strong></td>
                    <td><span class="tag tag-dim">${escapeHtml(inv.role)}</span></td>
                    <td><span class="tag ${inv.status === 'pending' ? 'tag-accent' : 'tag-dim'}">${escapeHtml(inv.status)}</span></td>
                      <td style="text-align:right;">
                        <button type="button" class="btn btn-ghost btn-sm btn-revoke-inv" data-id="${inv.id}" style="color:var(--bad);" ${inv.status === 'pending' ? '' : 'disabled'}>
                          ${t('team.revoke', {}, 'Revoke')}
                        </button>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          </div>
        `
            : ''
        }
      </div>
    `;
  },

  mounted: (ctx) => {
    document.getElementById('btn-invite-member')?.addEventListener('click', () => {
      openModal({
        title: t('team.invite_modal_title', {}, 'Invite Team Member'),
        content: `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <div class="field" style="margin:0;">
              <label>${t('team.email_label', {}, 'Work Email')} *</label>
              <input type="email" id="invite-email-input" class="input" placeholder="colleague@company.com" required>
            </div>
            <div class="field" style="margin:0;">
              <label>${t('common.role', {}, 'Role')}</label>
              <select id="invite-role-select" class="input">
                <option value="editor" selected>${t('team.role_editor_desc', {}, 'Editor (Can execute projects & tickets)')}</option>
                <option value="viewer">${t('team.role_viewer_desc', {}, 'Viewer (Read-only access)')}</option>
                <option value="owner">${t('team.role_owner_desc', {}, 'Owner (Full administrative rights)')}</option>
              </select>
            </div>
          </div>
        `,
        confirmText: t('team.send_invite', {}, 'Send Invitation'),
        onConfirm: async () => {
          const email = document.getElementById('invite-email-input')?.value.trim();
          const role = document.getElementById('invite-role-select')?.value;
          if (!email) return false;

          try {
            const result = await team.createInvitation({ email, role });
            pendingInviteUrl = new URL(result.invite_url, location.origin).href;
            toast.success(t('team.invite_created', {}, 'Invitation created!'));
            ctx.navigate(`#/team?updated=${Date.now()}`);
            return true;
          } catch (err) {
            toast.error(tError(err));
            return false;
          }
        },
      });
    });

    document.querySelectorAll('.btn-revoke-inv').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        try {
          await team.revokeInvitation(id);
          toast.success(t('team.invite_revoked', {}, 'Invitation revoked'));
          ctx.navigate('#/team');
        } catch (err) {
          toast.error(t('team.revoke_failed', {}, 'Failed to revoke invitation'));
        }
      });
    });

    if (pendingInviteUrl) {
      const url = pendingInviteUrl;
      pendingInviteUrl = '';
      showInvitationLink(url);
    }
  },
};

function showInvitationLink(url) {
  const result = openModal({
    title: t('team.invite_created', {}, 'Invitation Created'),
    showFooter: false,
    content: `
      <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
        <div class="field" style="margin:0;">
          <label>${t('team.invitation_link_label', {}, 'Invitation Link')}</label>
          <input type="text" id="created-invite-url" class="input" value="${escapeHtml(url)}" readonly>
        </div>
        <button type="button" id="copy-created-invite" class="btn btn-primary">${t('common.copy_link', {}, 'Copy Link')}</button>
      </div>
    `,
  });
  result.box.querySelector('#copy-created-invite')?.addEventListener('click', async () => {
    const input = result.box.querySelector('#created-invite-url');
    try {
      await navigator.clipboard.writeText(input.value);
      toast.success(t('team.invite_copied', {}, 'Invitation link copied'));
    } catch (e) {
      input.select();
      toast.error(t('team.copy_failed_manual', {}, 'Copy failed. Select and copy the link manually.'));
    }
  });
}
