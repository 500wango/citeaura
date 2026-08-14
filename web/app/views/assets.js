import { workspace } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }
    const assets = await workspace.getAssets(projectId).catch(() => []);
    if (!assets.length) {
      return `<div class="app-view-container">
        <div class="view-header"><div class="view-title-group"><h1 class="view-title">Generated Assets</h1><p class="view-desc">Review text assets generated for this brand.</p></div></div>
        ${renderEmpty({ title: 'No generated assets', description: 'Run the asset generation pipeline to create project-specific files.' })}
      </div>`;
    }
    const firstPath = assets[0].path;
    const first = await workspace.getAsset(projectId, firstPath).catch(() => ({ path: firstPath, text: '' }));
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group"><h1 class="view-title">Generated Assets</h1><p class="view-desc">Review and edit files generated from the current project workspace.</p></div>
          <div class="view-actions"><button type="button" id="btn-save-asset" class="btn btn-primary btn-sm">Save Asset</button></div>
        </div>
        <div class="card" style="gap:var(--sp-4);">
          <div class="field" style="margin:0;">
            <label for="asset-path">Asset file</label>
            <select id="asset-path" class="input">
              ${assets.map((item) => `<option value="${item.path}" ${item.path === first.path ? 'selected' : ''}>${item.path}</option>`).join('')}
            </select>
          </div>
          <div class="field" style="margin:0;">
            <label for="asset-text">File contents</label>
            <textarea id="asset-text" class="input" rows="24">${first.text || ''}</textarea>
          </div>
        </div>
      </div>`;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    const pathSelect = document.getElementById('asset-path');
    const editor = document.getElementById('asset-text');
    pathSelect?.addEventListener('change', async () => {
      const asset = await workspace.getAsset(projectId, pathSelect.value).catch(() => null);
      if (asset) editor.value = asset.text || '';
    });
    document.getElementById('btn-save-asset')?.addEventListener('click', async () => {
      try {
        await workspace.saveAsset(projectId, pathSelect.value, editor.value);
        toast.success('Asset saved');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to save asset'));
      }
    });
  },
};
