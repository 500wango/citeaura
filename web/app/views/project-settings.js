/**
 * 品牌设置视图 (Project Settings)
 */

import { projects, workspace } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { confirmModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let project = null;
    try {
      project = await projects.get(projectId).catch(() => null);
    } catch (e) {}

    if (!project) return `<div class="app-view-container">Brand not found</div>`;

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('project_settings.title', {}, 'Brand Workspace Settings')}</h1>
            <p class="view-desc">
              ${t('project_settings.desc', {}, 'Manage brand metadata, official crawl domain, language routing, and project retention.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-project-settings" class="btn btn-primary btn-sm">
              <span>${t('common.save_changes', {}, 'Save Settings')}</span>
            </button>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:var(--sp-6);max-width:680px;">
          <!-- 基础设置 -->
          <div class="card" style="gap:var(--sp-4);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('project_settings.general', {}, 'General Information')}</h3>

            <div class="field" style="margin:0;">
              <label>${t('project_settings.name_label', {}, 'Brand Display Name')}</label>
              <input type="text" id="proj-name-input" class="input" value="${project.name || project.slug}">
            </div>

            <div class="field" style="margin:0;">
              <label>${t('project_settings.url_label', {}, 'Official Website URL')}</label>
              <input type="url" id="proj-url-input" class="input" value="${project.url || ''}">
            </div>

            <div class="field" style="margin:0;">
              <label>${t('project_settings.market_label', {}, 'Target Market & Language Routing')}</label>
              <select id="proj-market-select" class="input">
                <option value="both" ${project.market === 'both' ? 'selected' : ''}>Universal (Global & Domestic Matrix)</option>
                <option value="global" ${project.market === 'global' ? 'selected' : ''}>English / Global Models Only</option>
                <option value="cn" ${project.market === 'cn' ? 'selected' : ''}>Chinese / Domestic Models Only</option>
              </select>
            </div>
          </div>

          <!-- 危险区 -->
          <div class="card" style="border-color:var(--bad);gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;color:var(--bad);">${t('common.danger_zone', {}, 'Danger Zone')}</h3>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Deleting a brand permanently deletes all workspace artifacts, historical sample logs, and generated tickets.
            </p>
            <button type="button" id="btn-delete-project" class="btn btn-danger btn-sm" style="align-self:flex-start;">
              ${t('project_settings.delete_btn', {}, 'Delete Brand Workspace')}
            </button>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-save-project-settings')?.addEventListener('click', async () => {
      const name = document.getElementById('proj-name-input')?.value.trim();
      const url = document.getElementById('proj-url-input')?.value.trim();
      const market = document.getElementById('proj-market-select')?.value;

      try {
        await workspace.patchConfig(projectId, { name, url, market });
        toast.success(t('project_settings.saved_success', {}, 'Brand settings updated'));
        await ctx.reloadProjects();
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to update settings'));
      }
    });

    document.getElementById('btn-delete-project')?.addEventListener('click', async () => {
      const confirmed = await confirmModal(
        t('project_settings.delete_confirm', {}, 'Are you sure you want to delete this brand workspace? This action cannot be undone.'),
        { isDanger: true, confirmText: t('common.delete', {}, 'Delete Workspace') }
      );
      if (!confirmed) return;

      try {
        await projects.delete(projectId);
        toast.success(t('project_settings.deleted_success', {}, 'Brand deleted'));
        await ctx.reloadProjects();
        ctx.navigate('#/overview');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to delete brand'));
      }
    });
  },
};
