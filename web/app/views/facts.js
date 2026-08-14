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

    const facts = await workspace.getFacts(projectId).catch(() => ({ exists: false, text: '' }));
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">Brand Fact Library</h1>
            <p class="view-desc">Maintain the official facts used by generated content and delivery assets. Include sources and verification dates for material claims.</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-facts" class="btn btn-primary btn-sm">Save Fact Library</button>
          </div>
        </div>
        <div class="card" style="gap:var(--sp-3);">
          <div class="field" style="margin:0;">
            <label for="facts-markdown">Official facts in Markdown</label>
            <textarea id="facts-markdown" class="input" rows="22" placeholder="# Brand facts\n\n## Definition\n\nWrite the approved one-sentence definition.\n\n## Verified claims\n\n- Claim - Source URL - Verified YYYY-MM-DD">${facts.text || ''}</textarea>
            <span style="font-size:var(--fs-1);color:var(--muted);">This file is stored as <code>content/facts.md</code>. CiteAura does not mark a claim as verified without a source you provide.</span>
          </div>
        </div>
      </div>`;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    document.getElementById('btn-save-facts')?.addEventListener('click', async () => {
      const text = document.getElementById('facts-markdown')?.value || '';
      try {
        await workspace.saveFacts(projectId, { text });
        toast.success('Brand fact library saved');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to save fact library'));
      }
    });
  },
};
