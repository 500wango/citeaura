import { projects, searchdata, workspace } from '../api.js';
import { t, tError } from '../i18n.js';
import { escapeHtml, safeHttpUrl } from '../safe-html.js';
import { toast } from '../components/toast.js';
import { confirmModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';
import { bindGa4Card, loadGa4Card, renderGa4Card } from '../components/ga4-connect.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    const [project, gsc, ga4] = await Promise.all([
      projects.get(projectId).catch(() => null),
      searchdata.getGsc(projectId).catch(() => null),
      loadGa4Card(projectId),
    ]);
    if (!project) return `<div class="app-view-container">${t('project_settings.not_found', {}, 'Project not found')}</div>`;
    const isOwner = ctx.role === 'owner';
    const isViewer = ctx.role === 'viewer';
    const ownerOnly = t('common.owner_only', {}, 'Only the workspace owner can make this change.');
    const viewerOnly = t('plan.viewer_read_only', {}, 'Viewer access: you can inspect evidence but cannot change tickets or plans.');
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('project_settings.title', {}, 'Project Settings')}</h1>
            <p class="view-desc">${t('project_settings.desc', {}, 'Update the canonical website URL, market routing, and question language. Report output stays English in this release.')}</p>
          </div>
          <div class="view-actions"><button type="button" id="btn-save-project-settings" class="btn btn-primary btn-sm" ${isViewer ? `disabled title="${escapeHtml(viewerOnly)}"` : ''}>${t('project_settings.save_btn', {}, 'Save Settings')}</button></div>
        </div>
        ${isViewer ? `<div class="read-only-note" role="status">${escapeHtml(viewerOnly)}</div>` : ''}
        <div style="display:flex;flex-direction:column;gap:var(--sp-6);max-width:680px;">
          <div class="card" style="gap:var(--sp-4);">
            <div class="field" style="margin:0;"><label>${t('project_settings.url_label', {}, 'Canonical website URL')}</label><input type="url" id="proj-url-input" class="input" value="${escapeHtml(safeHttpUrl(project.url) || project.url || '')}" ${isViewer ? 'readonly' : ''}></div>
            <div class="field" style="margin:0;">
              <label for="proj-market-input">${t('project_settings.market_label', {}, 'Market')}</label>
              <select id="proj-market-input" class="input" ${isViewer ? 'disabled' : ''}>
                <option value="global" ${project.market === 'global' ? 'selected' : ''}>${t('project_settings.market_global', {}, 'Global · English-first')}</option>
                <option value="cn" ${project.market === 'cn' ? 'selected' : ''}>${t('project_settings.market_cn', {}, 'China')}</option>
                <option value="both" ${project.market === 'both' ? 'selected' : ''}>${t('project_settings.market_both', {}, 'Both markets')}</option>
              </select>
              <div class="field-hint">${t('project_settings.market_hint', {}, 'Changing the market changes the engine cohort; existing samples are attributed separately.')}</div>
            </div>
            <div class="field" style="margin:0;">
              <label for="proj-language-input">${t('project_settings.question_language_label', {}, 'Question language')}</label>
              <select id="proj-language-input" class="input" ${isViewer ? 'disabled' : ''}>
                <option value="auto" ${(project.question_language || 'auto') === 'auto' ? 'selected' : ''}>${t('project_settings.language_auto', {}, 'Auto')}</option>
                <option value="en" ${project.question_language === 'en' ? 'selected' : ''}>English</option>
                <option value="zh" ${project.question_language === 'zh' ? 'selected' : ''}>简体中文</option>
                <option value="ja" ${project.question_language === 'ja' ? 'selected' : ''}>日本語</option>
                <option value="ko" ${project.question_language === 'ko' ? 'selected' : ''}>한국어</option>
                <option value="es" ${project.question_language === 'es' ? 'selected' : ''}>Español</option>
                <option value="fr" ${project.question_language === 'fr' ? 'selected' : ''}>Français</option>
                <option value="de" ${project.question_language === 'de' ? 'selected' : ''}>Deutsch</option>
              </select>
            </div>
          </div>
          ${gsc && (gsc.configured || gsc.status === 'ready') ? `<div class="card" style="gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('gsc.settings_title', {}, 'Google Search Console data')}</h3>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">${t('gsc.settings_desc', {}, 'CiteAura reads Search Console once per authorization and does not keep your Google credentials. Only the query snapshot below is stored in this project.')}</p>
            ${gsc.status === 'ready'
              ? `<div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;font-size:var(--fs-2);"><span class="num">${escapeHtml(gsc.property)}</span><span style="color:var(--muted);">${t('gsc.fetched_at', { time: new Date(gsc.fetched_at).toLocaleString() }, `Fetched ${new Date(gsc.fetched_at).toLocaleString()}`)}</span></div>
                 <button type="button" id="btn-settings-gsc-delete" class="btn btn-secondary btn-sm" style="align-self:flex-start;" ${isViewer ? `disabled title="${escapeHtml(viewerOnly)}"` : ''}>${t('gsc.delete_btn', {}, 'Delete Search Console data')}</button>`
              : `<a href="#/questions" class="btn btn-secondary btn-sm" style="align-self:flex-start;">${t('gsc.connect_btn', {}, 'Connect Search Console')}</a>`}
          </div>` : ''}
          ${renderGa4Card(ga4, { isViewer, readOnlyReason: viewerOnly })}
          <div class="card" style="border-color:var(--bad);gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;color:var(--bad);">${t('project_settings.archive_title', {}, 'Archive project')}</h3>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">${t('project_settings.archive_desc', {}, 'Archiving removes the project from the active workspace list and keeps filesystem artifacts on disk. It does not permanently delete files.')}</p>
            <button type="button" id="btn-delete-project" class="btn btn-danger btn-sm" style="align-self:flex-start;" ${isOwner ? '' : `disabled title="${escapeHtml(ownerOnly)}"`}>${t('project_settings.archive_btn', {}, 'Archive Project')}</button>
          </div>
        </div>
      </div>`;
  },
  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (ctx.role !== 'viewer') document.getElementById('btn-save-project-settings')?.addEventListener('click', async () => {
      const url = document.getElementById('proj-url-input')?.value.trim();
      const market = document.getElementById('proj-market-input')?.value;
      const questionLanguage = document.getElementById('proj-language-input')?.value;
      try {
        await workspace.patchConfig(projectId, {
          url, market, question_language: questionLanguage,
        });
        toast.success(t('project_settings.updated', {}, 'Project settings updated'));
        await ctx.reloadProjects();
      } catch (err) {
        toast.error(tError(err));
      }
    });
    if (ctx.role !== 'viewer') document.getElementById('btn-settings-gsc-delete')?.addEventListener('click', async () => {
      const confirmed = await confirmModal(t('gsc.delete_desc', {}, 'This removes the stored query snapshot for this project. Questions already added to the bank stay, including their recorded Google figures.'), { isDanger: true, confirmText: t('gsc.delete_btn', {}, 'Delete Search Console data') });
      if (!confirmed) return;
      try {
        await searchdata.deleteGsc(projectId);
        toast.success(t('gsc.deleted', {}, 'Search Console data deleted'));
        await ctx.reloadCurrentView();
      } catch (err) {
        toast.error(tError(err));
      }
    });
    bindGa4Card(ctx, projectId);
    if (ctx.role === 'owner') document.getElementById('btn-delete-project')?.addEventListener('click', async () => {
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
