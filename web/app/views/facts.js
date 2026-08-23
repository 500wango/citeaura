import { workspace } from '../api.js?v=3.4';
import { t, tError } from '../i18n.js';
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
        <div><strong>${t('facts.review_required', {}, 'Review required.')}</strong> ${t('facts.migration_rebuilt', {}, 'This historical library was rebuilt in English from structured official-site evidence. Confirm incomplete fields before using it in published assets.')}</div>
      </div>`;
  }
  if (status === 'ai_regenerated') {
    return `
      <div class="banner good" style="margin-bottom:var(--sp-4);">
        <div>${t('facts.legacy_replaced', {}, 'The legacy library was replaced by a current English AI extraction. Review its evidence before publishing.')}</div>
      </div>`;
  }
  if (status === 'manual_translation_required') {
    return `
      <div class="banner warn" style="margin-bottom:var(--sp-4);">
        <div><strong>${t('facts.manual_trans_required', {}, 'Manual translation required.')}</strong> ${t('facts.manual_trans_desc', {}, 'This user-maintained library contains non-English text and was preserved unchanged. Replace it with evidence-backed English content before saving.')}</div>
      </div>`;
  }
  return '';
}

function reviewStatusNotice(facts) {
  if (facts?.reviewed) {
    return `
      <div class="banner good" style="margin-bottom:var(--sp-4);">
        <div><strong>${t('facts.approved_notice', {}, 'Approved for derived assets.')}</strong> ${t('facts.approved_notice_desc', {}, 'Saving with approval enabled will keep generated JSON-LD, /llms.txt, and definition assets eligible for deployment.')}</div>
      </div>`;
  }
  if (facts?.machine_verified) {
    const verified = Number(facts?.verification?.verified || 0);
    const needsHuman = Number(facts?.verification?.needs_human || 0);
    return `
      <div class="banner good" style="margin-bottom:var(--sp-4);">
        <div><strong>${t('facts.machine_verified_title', {}, 'Machine-verified against the official website.')}</strong> ${verified} publication claim(s) matched crawl evidence. Derived /llms.txt, JSON-LD, and definition assets can be published. ${needsHuman ? `${needsHuman} inferred statement(s) stay out of publishable copy until a human confirms them.` : ''}</div>
      </div>`;
  }
  return `
    <div class="banner warn" style="margin-bottom:var(--sp-4);">
      <div><strong>${t('facts.not_grounded_title', {}, 'Not yet grounded.')}</strong> ${t('facts.not_grounded_desc', {}, 'CiteAura verifies claims by matching them to official-site crawl text. It does not ask the model to grade its own extraction. Add source-backed values or keep inferred statements out of published assets.')}</div>
    </div>`;
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
            <h1 class="view-title">${t('facts.title', {}, 'Brand Fact Library')}</h1>
            <p class="view-desc">${t('facts.desc', {}, 'CiteAura extracts facts from the official site, then verifies them against the crawl. The checkbox is only a human override. Inferred or paraphrased claims stay unpublished until they appear on the site or you approve them.')}</p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-facts" class="btn btn-primary btn-sm">${t('facts.save_btn', {}, 'Save Fact Library')}</button>
          </div>
        </div>
        ${migrationNotice(facts)}
        ${reviewStatusNotice(facts)}
        <div class="card" style="gap:var(--sp-3);">
          <div class="field" style="margin:0;">
            <label for="facts-markdown">${t('facts.markdown_label', {}, 'Official facts in Markdown')}</label>
            <textarea id="facts-markdown" class="input" rows="22" placeholder="# Brand facts\n\n## Definition\n\nWrite the approved one-sentence definition.\n\n## Verified claims\n\n- Claim - Source URL - Verified YYYY-MM-DD">${escapeHtml(facts.text || '')}</textarea>
            <span style="font-size:var(--fs-1);color:var(--muted);">${t('facts.markdown_tip', {}, 'This file is stored as <code>content/facts.md</code>. CiteAura does not mark a claim as verified without a source you provide.')}</span>
          </div>
          <label style="display:flex;align-items:flex-start;gap:var(--sp-2);font-size:var(--fs-2);">
            <input type="checkbox" id="facts-approve" ${facts.reviewed ? 'checked' : ''}>
            <span>${t('facts.approval_checkbox', {}, 'I reviewed every material claim, attached evidence, and approve this library for publishable derived assets. The diagnostic pack does not need this checkbox.')}</span>
          </label>
        </div>
      </div>`;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    document.getElementById('btn-save-facts')?.addEventListener('click', async () => {
      const text = document.getElementById('facts-markdown')?.value || '';
      const approve = Boolean(document.getElementById('facts-approve')?.checked);
      try {
        await workspace.saveFacts(projectId, { text, approve });
        toast.success(t('facts.saved_success', {}, 'Brand fact library saved'));
      } catch (err) {
        toast.error(tError(err));
      }
    });
  },
};
