/**
 * 协作外联与草稿发送视图 (Outreach & Media Pitches)
 */

import { outreach } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let outreachData = {};
    try {
      outreachData = await outreach.get(projectId).catch(() => ({}));
    } catch (e) {}

    const drafts = outreachData.drafts || [];
    const hasSmtp = outreachData.has_smtp || false;

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('outreach.title', {}, 'Media Outreach & Citation Pitches')}</h1>
            <p class="view-desc">
              ${t('outreach.desc', {}, 'Draft and dispatch factual pitch emails to directory editors and review authors cited by LLM search results.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-config-smtp" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              <span>${hasSmtp ? t('outreach.smtp_configured', {}, 'SMTP Configured') : t('outreach.setup_smtp', {}, 'Configure SMTP')}</span>
            </button>
            <button type="button" id="btn-new-draft" class="btn btn-primary btn-sm">
              + ${t('outreach.new_pitch_btn', {}, 'New Pitch Draft')}
            </button>
          </div>
        </div>

        <!-- 外联草稿列表 -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('outreach.drafts_head', {}, 'Outreach Pitch Queue')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${drafts.length} drafts</span>
          </div>

          ${
            drafts.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('outreach.col_recipient', {}, 'Recipient')}</th>
                    <th>${t('outreach.col_subject', {}, 'Subject Line')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${drafts
                    .map(
                      (d) => `
                    <tr>
                      <td><strong class="num">${d.recipient}</strong></td>
                      <td>${d.subject}</td>
                      <td><span class="tag ${d.status === 'sent' ? 'pill-good' : 'tag-dim'}">${d.status || 'draft'}</span></td>
                      <td style="text-align:right;">
                        <button type="button" class="btn btn-primary btn-sm btn-send-draft" data-id="${d.id}" data-rec="${d.recipient}" data-sub="${d.subject}">
                          ${t('outreach.review_send', {}, 'Review & Send')}
                        </button>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
                ${renderEmpty({
                  title: t('outreach.no_drafts', {}, 'No Outreach Drafts'),
                  description: t('outreach.no_drafts_desc', {}, 'Create outreach pitches to request authoritative citation mentions from industry blogs and directories.'),
                  actionText: t('outreach.new_pitch_btn', {}, 'New Pitch Draft'),
                  onAction: () => document.getElementById('btn-new-draft')?.click(),
                })}
              </div>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    // SMTP 配置弹窗
    document.getElementById('btn-config-smtp')?.addEventListener('click', () => {
      const content = `
        <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
          <div class="field" style="margin:0;">
            <label>SMTP Host *</label>
            <input type="text" id="smtp-host" class="input" placeholder="smtp.mailgun.org" required>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-3);">
            <div class="field" style="margin:0;">
              <label>Port</label>
              <input type="number" id="smtp-port" class="input" value="587">
            </div>
            <div class="field" style="margin:0;">
              <label>From Email *</label>
              <input type="email" id="smtp-from" class="input" placeholder="outreach@yourbrand.com">
            </div>
          </div>
          <div class="field" style="margin:0;">
            <label>Username / API Key</label>
            <input type="text" id="smtp-user" class="input" placeholder="postmaster@yourdomain.com">
          </div>
          <div class="field" style="margin:0;">
            <label>Password / Secret</label>
            <input type="password" id="smtp-pass" class="input" placeholder="••••••••">
          </div>
        </div>
      `;

      openModal({
        title: t('outreach.smtp_modal_title', {}, 'Outreach SMTP Server Settings'),
        content,
        confirmText: t('common.save', {}, 'Save Credentials'),
        onConfirm: async () => {
          const host = document.getElementById('smtp-host')?.value.trim();
          const port = parseInt(document.getElementById('smtp-port')?.value || '587');
          const from_email = document.getElementById('smtp-from')?.value.trim();
          const username = document.getElementById('smtp-user')?.value.trim();
          const password = document.getElementById('smtp-pass')?.value;

          if (!host || !from_email) return false;

          try {
            await outreach.saveSmtp(projectId, { host, port, from_email, username, password });
            toast.success(t('outreach.smtp_saved', {}, 'SMTP credentials saved securely (AES-256-GCM)'));
            ctx.navigate('#/outreach');
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to save SMTP settings'));
            return false;
          }
        },
      });
    });

    // 发送审核弹窗（硬约束：人工确认）
    document.querySelectorAll('.btn-send-draft').forEach((btn) => {
      btn.addEventListener('click', () => {
        const draftId = btn.getAttribute('data-id');
        const rec = btn.getAttribute('data-rec');
        const sub = btn.getAttribute('data-sub');

        const content = `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <div class="banner warn">
              <strong>Human Confirmation Required:</strong> Emails are sent live to recipients. Please verify the destination and message accuracy.
            </div>
            <div>
              <span style="font-size:12px;color:var(--muted);">Recipient:</span>
              <strong style="display:block;font-size:var(--fs-3);">${rec}</strong>
            </div>
            <div>
              <span style="font-size:12px;color:var(--muted);">Subject:</span>
              <div style="font-size:var(--fs-2);font-weight:600;">${sub}</div>
            </div>
            <div class="field" style="margin-top:var(--sp-2);">
              <label>Type <code>SEND ${draftId}</code> to confirm dispatch:</label>
              <input type="text" id="confirm-send-text" class="input" placeholder="SEND ${draftId}">
            </div>
          </div>
        `;

        openModal({
          title: t('outreach.confirm_send_title', {}, 'Confirm Dispatch'),
          content,
          confirmText: t('outreach.dispatch_btn', {}, 'Dispatch Email'),
          isDanger: true,
          onConfirm: async () => {
            const inputVal = document.getElementById('confirm-send-text')?.value.trim();
            if (inputVal !== `SEND ${draftId}`) {
              toast.error('Confirmation text does not match');
              return false;
            }

            try {
              await outreach.sendDraft(projectId, draftId, { confirmation_text: inputVal });
              toast.success(t('outreach.sent_success', {}, 'Email dispatched successfully'));
              ctx.navigate('#/outreach');
              return true;
            } catch (err) {
              toast.error(t(err.error, {}, err.detail || 'Failed to dispatch draft'));
              return false;
            }
          },
        });
      });
    });
  },
};
