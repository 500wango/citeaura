/**
 * 竞品分析视图 (Competitors)
 */

import { workspace } from '../api.js';
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

    let config = {};
    try {
      config = await workspace.getConfig(projectId).catch(() => ({}));
    } catch (e) {}

    const competitors = config.competitors || [];

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('competitors.title', {}, 'Competitor Benchmark')}</h1>
            <p class="view-desc">
              ${t('competitors.desc', {}, 'Track competitor recommendation frequency in generative AI search and discover emergent rivals cited in sample answers.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-add-competitor" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('competitors.add_btn', {}, 'Add Competitor')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('competitors.list_title', {}, 'Monitored Competitors')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${competitors.length} ${t('common.competitors_total', {}, 'competitors')}</span>
          </div>

          ${
            competitors.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>${t('competitors.col_name', {}, 'Competitor Name')}</th>
                    <th>${t('competitors.col_domain', {}, 'Domain URL')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${competitors
                    .map((comp, idx) => {
                      const name = typeof comp === 'string' ? comp : comp.name;
                      const domain = typeof comp === 'object' ? comp.domain || comp.url : '—';
                      return `
                      <tr>
                        <td class="num" style="color:var(--muted);">${idx + 1}</td>
                        <td><strong style="font-size:var(--fs-3);">${name}</strong></td>
                        <td class="num" style="color:var(--muted);">${domain || '—'}</td>
                        <td style="text-align:right;">
                          <button type="button" class="btn btn-ghost btn-sm btn-del-comp" data-comp="${name}" style="color:var(--bad);">
                            ${t('common.remove', {}, 'Remove')}
                          </button>
                        </td>
                      </tr>
                    `;
                    })
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);">
                ${renderEmpty({
                  title: t('competitors.no_competitors', {}, 'No Competitors Configured'),
                  description: t('competitors.no_competitors_desc', {}, 'Add your top industry competitors to compare recommendation shares across AI search engines.'),
                  actionText: t('competitors.add_btn', {}, 'Add Competitor'),
                  onAction: () => document.getElementById('btn-add-competitor')?.click(),
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

    const addBtn = document.getElementById('btn-add-competitor');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        const content = `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <div class="field" style="margin:0;">
              <label>${t('competitors.comp_name_label', {}, 'Competitor Brand Name')} *</label>
              <input type="text" id="new-comp-name" class="input" placeholder="e.g. RivalCo" required>
            </div>
            <div class="field" style="margin:0;">
              <label>${t('competitors.comp_domain_label', {}, 'Website Domain')}</label>
              <input type="url" id="new-comp-domain" class="input" placeholder="https://rival.com">
            </div>
          </div>
        `;

        openModal({
          title: t('competitors.add_modal_title', {}, 'Add Competitor'),
          content,
          confirmText: t('common.add', {}, 'Add Competitor'),
          onConfirm: async () => {
            const name = document.getElementById('new-comp-name')?.value.trim();
            const domain = document.getElementById('new-comp-domain')?.value.trim();
            if (!name) return false;

            try {
              const currentConfig = await workspace.getConfig(projectId).catch(() => ({}));
              const currentList = currentConfig.competitors || [];
              const updated = [...currentList, { name, domain }];
              await workspace.patchConfig(projectId, { competitors: updated });
              toast.success(t('competitors.added_success', {}, 'Competitor added'));
              ctx.navigate('#/competitors');
              return true;
            } catch (err) {
              toast.error(t(err.error, {}, err.detail || 'Failed to add competitor'));
              return false;
            }
          },
        });
      });
    }

    document.querySelectorAll('.btn-del-comp').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const compName = btn.getAttribute('data-comp');
        try {
          const currentConfig = await workspace.getConfig(projectId).catch(() => ({}));
          const currentList = currentConfig.competitors || [];
          const updated = currentList.filter((c) => (typeof c === 'string' ? c !== compName : c.name !== compName));
          await workspace.patchConfig(projectId, { competitors: updated });
          toast.success(t('competitors.removed_success', {}, 'Competitor removed'));
          ctx.navigate('#/competitors');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to remove competitor'));
        }
      });
    });
  },
};
