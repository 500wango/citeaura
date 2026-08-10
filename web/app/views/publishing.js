/**
 * 内容发布渠道视图 (Publishing Destinations)
 */

import { publishing } from '../api.js';
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

    let pubConfig = {};
    try {
      pubConfig = await publishing.get(projectId).catch(() => ({}));
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('publishing.title', {}, 'Publishing Destinations')}</h1>
            <p class="view-desc">
              ${t('publishing.desc', {}, 'Push structured optimization content and FAQ articles directly into your CMS as draft posts for editorial review.')}
            </p>
          </div>
        </div>

        <div class="banner warn">
          <strong>Drafts Only:</strong> CiteAura creates draft content only. We never publish directly to live production websites without your team's editorial review.
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:var(--sp-6);">
          <!-- WordPress -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-4);">WordPress REST API</strong>
              <span class="tag ${pubConfig.wordpress?.configured ? 'pill-good' : 'tag-dim'}">
                ${pubConfig.wordpress?.configured ? 'Configured' : 'Not Connected'}
              </span>
            </div>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Connect via WordPress Application Password to push GEO articles as pending review drafts.
            </p>
            <button type="button" class="btn btn-secondary btn-sm btn-config-wp" style="align-self:flex-start;">
              ${t('publishing.config_btn', {}, 'Configure WordPress')}
            </button>
          </div>

          <!-- WeChat Official Account -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-4);">WeChat Official Account</strong>
              <span class="tag ${pubConfig.wechat?.configured ? 'pill-good' : 'tag-dim'}">
                ${pubConfig.wechat?.configured ? 'Configured' : 'Not Connected'}
              </span>
            </div>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Push generated FAQ knowledge articles into your WeChat draft box (草稿箱) for mobile readers.
            </p>
            <button type="button" class="btn btn-secondary btn-sm btn-config-wechat" style="align-self:flex-start;">
              ${t('publishing.config_btn', {}, 'Configure WeChat')}
            </button>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.querySelector('.btn-config-wp')?.addEventListener('click', () => {
      const content = `
        <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
          <div class="field" style="margin:0;">
            <label>WordPress Site URL *</label>
            <input type="url" id="wp-url" class="input" placeholder="https://yourblog.com">
          </div>
          <div class="field" style="margin:0;">
            <label>Application Username *</label>
            <input type="text" id="wp-user" class="input" placeholder="admin">
          </div>
          <div class="field" style="margin:0;">
            <label>Application Password *</label>
            <input type="password" id="wp-pass" class="input" placeholder="•••• •••• •••• ••••">
          </div>
        </div>
      `;

      openModal({
        title: 'Configure WordPress Publishing',
        content,
        confirmText: 'Save WordPress Settings',
        onConfirm: async () => {
          const site_url = document.getElementById('wp-url')?.value.trim();
          const username = document.getElementById('wp-user')?.value.trim();
          const password = document.getElementById('wp-pass')?.value.trim();
          if (!site_url || !username || !password) return false;

          try {
            await publishing.save(projectId, 'wordpress', { site_url, username, password });
            toast.success('WordPress publishing credentials saved');
            ctx.navigate('#/publishing');
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to save settings'));
            return false;
          }
        },
      });
    });
  },
};
