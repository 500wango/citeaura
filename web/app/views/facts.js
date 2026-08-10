/**
 * 品牌事实库视图 (Brand Facts Library)
 */

import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';
import { setSafeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let factsData = {};
    try {
      factsData = await workspace.getFacts(projectId).catch(() => ({}));
    } catch (e) {}

    const definition = factsData.definition || factsData.one_sentence || '';
    const factsList = factsData.facts || factsData.items || [];

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('facts.title', {}, 'Brand Fact Library & Truth Cards')}</h1>
            <p class="view-desc">
              ${t('facts.desc', {}, 'Standardize your one-sentence brand definition and verified numeric facts to eliminate hallucination in AI models.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-facts" class="btn btn-primary btn-sm">
              <span>${t('common.save_changes', {}, 'Save Fact Library')}</span>
            </button>
          </div>
        </div>

        <!-- 一句话核心定义 -->
        <div class="card" style="gap:var(--sp-3);">
          <div class="kicker">Core Entity Definition</div>
          <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('facts.one_sentence_head', {}, 'Standard One-Sentence Brand Definition')}</h3>
          <p style="font-size:var(--fs-2);color:var(--muted);margin:0;">
            ${t('facts.one_sentence_tip', {}, 'Must be verbatim identical across 4 surfaces: Homepage Hero, About page, OpenGraph metadata, and /llms.txt.')}
          </p>
          <textarea id="fact-definition-input" class="input" rows="3" placeholder="CiteAura is the next-generation Generative Engine Optimization (GEO) platform that audits AI visibility gaps and exports actionable engineering tickets.">${definition}</textarea>
        </div>

        <!-- 结构化事实卡列表 -->
        <div class="card" style="gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('facts.numeric_facts_head', {}, 'Verified Numeric Facts & Entities')}</h3>
            <button type="button" id="btn-add-fact-item" class="btn btn-secondary btn-sm">
              + ${t('facts.add_fact_item', {}, 'Add Fact Card')}
            </button>
          </div>

          <div id="facts-container" style="display:flex;flex-direction:column;gap:var(--sp-3);">
            ${
              factsList.length
                ? factsList
                    .map(
                      (f, idx) => `
                  <div class="card fact-row" style="background:var(--page);padding:var(--sp-3);gap:var(--sp-2);">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-2);">
                      <input type="text" class="input fact-claim" value="${f.claim || f.title || ''}" placeholder="Fact Claim (e.g. Over 500+ active brand audits)" style="font-weight:600;">
                      <select class="input fact-grade" style="width:140px;flex:none;">
                        <option value="Gold" ${f.grade === 'Gold' ? 'selected' : ''}>Gold (Official)</option>
                        <option value="Silver" ${f.grade === 'Silver' ? 'selected' : ''}>Silver (Third-party)</option>
                        <option value="Bronze" ${f.grade === 'Bronze' ? 'selected' : ''}>Bronze (Claim)</option>
                      </select>
                      <button type="button" class="btn btn-ghost btn-sm btn-remove-fact" style="color:var(--bad);">✕</button>
                    </div>
                  </div>
                `
                    )
                    .join('')
                : `
                <div class="card fact-row" style="background:var(--page);padding:var(--sp-3);gap:var(--sp-2);">
                  <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-2);">
                    <input type="text" class="input fact-claim" value="Founded in 2026, specialized in GEO measurement" placeholder="Fact Claim" style="font-weight:600;">
                    <select class="input fact-grade" style="width:140px;flex:none;">
                      <option value="Gold" selected>Gold (Official)</option>
                      <option value="Silver">Silver (Third-party)</option>
                    </select>
                    <button type="button" class="btn btn-ghost btn-sm btn-remove-fact" style="color:var(--bad);">✕</button>
                  </div>
                </div>
              `
            }
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    const container = document.getElementById('facts-container');
    document.getElementById('btn-add-fact-item')?.addEventListener('click', () => {
      const row = document.createElement('div');
      row.className = 'card fact-row';
      row.style.background = 'var(--page)';
      row.style.padding = 'var(--sp-3)';
      setSafeHtml(row, `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-2);">
          <input type="text" class="input fact-claim" placeholder="Fact Claim..." style="font-weight:600;">
          <select class="input fact-grade" style="width:140px;flex:none;">
            <option value="Gold" selected>Gold (Official)</option>
            <option value="Silver">Silver (Third-party)</option>
            <option value="Bronze">Bronze (Claim)</option>
          </select>
          <button type="button" class="btn btn-ghost btn-sm btn-remove-fact" style="color:var(--bad);">✕</button>
        </div>
      `);
      row.querySelector('.btn-remove-fact').addEventListener('click', () => row.remove());
      container.appendChild(row);
    });

    document.querySelectorAll('.btn-remove-fact').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.target.closest('.fact-row')?.remove();
      });
    });

    document.getElementById('btn-save-facts')?.addEventListener('click', async () => {
      const definition = document.getElementById('fact-definition-input')?.value.trim();
      const facts = [];
      document.querySelectorAll('.fact-row').forEach((row) => {
        const claim = row.querySelector('.fact-claim')?.value.trim();
        const grade = row.querySelector('.fact-grade')?.value;
        if (claim) facts.push({ claim, grade });
      });

      try {
        await workspace.saveFacts(projectId, { definition, facts });
        toast.success(t('facts.saved_success', {}, 'Brand facts saved successfully'));
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to save facts'));
      }
    });
  },
};
