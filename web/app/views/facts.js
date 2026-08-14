import { workspace } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function migrationNotice(facts) {
  const status = facts?.migration?.status;
  if (status === 'evidence_rebuilt') {
    return `
      <div class="banner warn" style="margin-bottom:var(--sp-4);">
        <div><strong>Review required.</strong> This historical library was rebuilt in English from structured official-site evidence. Confirm incomplete fields before using it in published assets.</div>
      </div>`;
  }
  if (status === 'ai_regenerated') {
    return `
      <div class="banner good" style="margin-bottom:var(--sp-4);">
        <div>The legacy library was replaced by a current English AI extraction. Review its evidence before publishing.</div>
      </div>`;
  }
  if (status === 'manual_translation_required') {
    return `
      <div class="banner warn" style="margin-bottom:var(--sp-4);">
        <div><strong>Manual translation required.</strong> This user-maintained library contains non-English text and was preserved unchanged. Replace it with evidence-backed English content before saving.</div>
      </div>`;
  }
  return '';
}

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
        ${migrationNotice(facts)}
        <div class="card" style="gap:var(--sp-3);">
          <div class="field" style="margin:0;">
            <label for="facts-markdown">Official facts in Markdown</label>
            <textarea id="facts-markdown" class="input" rows="22" placeholder="# Brand facts\n\n## Definition\n\nWrite the approved one-sentence definition.\n\n## Verified claims\n\n- Claim - Source URL - Verified YYYY-MM-DD">${escapeHtml(facts.text || '')}</textarea>
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
