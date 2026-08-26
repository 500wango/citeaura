import { projects, workspace } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { confirmModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const project = await projects.get(projectId).catch(() => null);
    if (!project) return `<div class="app-view-container">${t('project_settings.not_found', {}, 'Project not found')}</div>`;
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('project_settings.title', {}, 'Project Settings')}</h1>
            <p class="view-desc">${t('project_settings.desc', {}, 'Update the canonical website URL used for future crawls. Project language routing is automatic and not user-configurable.')}</p>
          </div>
          <div class="view-actions"><button type="button" id="btn-save-project-settings" class="btn btn-primary btn-sm">${t('project_settings.save_btn', {}, 'Save Settings')}</button></div>
        </div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-6);max-width:680px;">
          <div class="card" style="gap:var(--sp-4);">
            <div class="field" style="margin:0;"><label>${t('project_settings.url_label', {}, 'Canonical website URL')}</label><input type="url" id="proj-url-input" class="input" value="${project.url || ''}"></div>
          </div>
          <div class="card" style="border-color:var(--bad);gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;color:var(--bad);">${t('project_settings.archive_title', {}, 'Archive project')}</h3>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">${t('project_settings.archive_desc', {}, 'Archiving removes the project from the active workspace list and keeps filesystem artifacts on disk. It does not permanently delete files.')}</p>
            <button type="button" id="btn-delete-project" class="btn btn-danger btn-sm" style="align-self:flex-start;">${t('project_settings.archive_btn', {}, 'Archive Project')}</button>
          </div>
        </div>
      </div>`;
  },
  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    document.getElementById('btn-save-project-settings')?.addEventListener('click', async () => {
      const url = document.getElementById('proj-url-input')?.value.trim();
      try {
        await workspace.patchConfig(projectId, { url });
        toast.success(t('project_settings.updated', {}, 'Project settings updated'));
        await ctx.reloadProjects();
      } catch (err) {
        toast.error(tError(err));
      }
    });
    document.getElementById('btn-delete-project')?.addEventListener('click', async () => {
      const confirmed = await confirmModal(t('project_settings.archive_confirm', {}, 'Archive this project? Files will remain on disk and the project can be recreated after cleanup or restore.'), { isDanger: true, confirmText: t('project_settings.archive_btn', {}, 'Archive project') });
      if (!confirmed) return;
      try {
        await projects.delete(projectId);
        toast.success(t('project_settings.archived', {}, 'Project archived'));
        await ctx.reloadProjects();
        ctx.navigate('#/overview');
      } catch (err) {
        toast.error(tError(err));
      }
    });
  },
};
