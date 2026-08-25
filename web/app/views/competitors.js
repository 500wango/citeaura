/**
 *  (Competitors)
 */

import { workspace, projects } from '../api.js?v=3.4';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let config = {};
    let discovery = {};
    let insights = {};
    try {
      const project = await projects.get(projectId).catch(() => null);
      config = await workspace.getConfig(projectId).catch(() => ({}));
      discovery = project?.competitor_discovery || {};
      insights = project?.insights || {};
    } catch (e) {}

    const competitors = config.competitors || [];
    const discoveryByName = Object.fromEntries(
      (discovery.items || []).map((item) => [item.name, item]),
    );
    const heatmap = insights.competitor_heatmap || {};
    const entities = Array.isArray(heatmap.entities) ? heatmap.entities : [];
    const cohorts = Array.isArray(heatmap.cohorts) ? heatmap.cohorts : [];
    const heatmapQuestions = Array.isArray(heatmap.questions) ? heatmap.questions : [];
    const alerts = Array.isArray(insights.takeover_alerts) ? insights.takeover_alerts : [];
    const cellLabel = (cell) => {
      if (!cell || cell.samples === 0 || cell.rate === null || cell.rate === undefined) return '—';
      return `${Math.round(cell.rate * 100)}% (n=${cell.samples})`;
    };

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('competitors.title', {}, 'Competitor Benchmark')}</h1>
            <p class="view-desc">
              ${t('competitors.desc', {}, 'Track evidence-classified direct competitors and their recommendation frequency in generative AI search.')}
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
                    <th>${t('competitors.col_relationship', {}, 'Relationship')}</th>
                    <th>${t('competitors.col_evidence', {}, 'Evidence')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${competitors
                    .map((comp, idx) => {
                      const name = typeof comp === 'string' ? comp : comp.name;
                      const domain = typeof comp === 'object' ? comp.domain || comp.url : '—';
                      const relationship = typeof comp === 'object' ? comp.relationship || 'direct_competitor' : 'direct_competitor';
                      const discovered = discoveryByName[name] || {};
                      const evidence = discovered.discovery_status || (
                        typeof comp === 'object' && comp.relationship_review_required !== false ? t('common.review_required', {}, 'Review required') : t('common.confirmed', {}, 'Confirmed')
                      );
                      return `
                      <tr>
                        <td class="num" style="color:var(--muted);">${idx + 1}</td>
                        <td><strong style="font-size:var(--fs-3);">${escapeHtml(name || '')}</strong></td>
                        <td class="num" style="color:var(--muted);">${escapeHtml(domain || '—')}</td>
                        <td>${escapeHtml(relationship === 'direct_competitor' ? 'Direct competitor' : relationship)}</td>
                        <td>${escapeHtml(evidence)}</td>
                        <td style="text-align:right;">
                          <button type="button" class="btn btn-ghost btn-sm btn-del-comp" data-comp="${escapeHtml(name || '')}" style="color:var(--bad);">
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

        <div class="card" style="padding:0;overflow:hidden;margin-top:var(--sp-4);">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);">
            <div>
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0 0 4px;">${t('competitors.heatmap_title', {}, 'Recommendation Heatmap')}</h3>
              <p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('competitors.heatmap_desc', {}, 'Question × entity × sampling cohort. API cohorts and product-surface observations stay separate.')}</p>
            </div>
            <span class="tag tag-neutral">${heatmap.sample_count || 0} ${t('common.valid_samples', {}, 'valid samples')}</span>
          </div>
          ${alerts.length ? `<div style="padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--line);background:var(--bad-soft);color:var(--bad);font-size:var(--fs-2);"><strong>${escapeHtml(t('competitors.takeover_alert', { count: alerts.length }, '{count} takeover candidate(s)'))}</strong></div>` : ''}
          ${cohorts.length && entities.length && heatmapQuestions.length ? cohorts.map((cohort) => {
            const cohortKey = cohort.key;
            return `<div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
              <div style="display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-3);"><strong>${escapeHtml(cohort.engine_name || cohort.engine_code)}</strong><span class="tag tag-dim">${escapeHtml(cohort.sampling_mode || '')}</span><span class="num" style="color:var(--muted);font-size:var(--fs-1);">n=${cohort.samples || 0}</span></div>
              <div class="tbl" style="overflow-x:auto;"><table class="table"><thead><tr><th>${t('questions.col_prompt', {}, 'Prompt')}</th>${entities.map((entity) => `<th style="text-align:right;">${escapeHtml(entity.name)}</th>`).join('')}</tr></thead><tbody>${heatmapQuestions.map((question) => {
                const cells = ((question.cohorts || []).find((item) => item.cohort === cohortKey) || {}).cells || {};
                return `<tr><td style="min-width:260px;"><strong>${escapeHtml(question.text || question.id)}</strong><div class="num" style="color:var(--muted);font-size:var(--fs-1);">${escapeHtml(question.id || '')}</div></td>${entities.map((entity) => {
                  const cell = cells[entity.key];
                  const isAlert = alerts.some((alert) => alert.question_id === question.id && alert.cohort === cohortKey && ((alert.competitor === entity.name) || entity.key === 'brand'));
                  return `<td data-num style="${isAlert ? 'color:var(--bad);font-weight:700;' : ''}">${cellLabel(cell)}</td>`;
                }).join('')}</tr>`;
              }).join('')}</tbody></table></div>
            </div>`;
          }).join('') : `<div style="padding:var(--sp-6);color:var(--muted);font-size:var(--fs-2);">${t('competitors.heatmap_empty', {}, 'Add competitors and run a sample to populate the recommendation heatmap.')}</div>`}
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
              <label for="new-comp-name">${t('competitors.comp_name_label', {}, 'Competitor Brand Name')} *</label>
              <input type="text" id="new-comp-name" class="input" placeholder="e.g. RivalCo" required>
            </div>
            <div class="field" style="margin:0;">
              <label for="new-comp-domain">${t('competitors.comp_domain_label', {}, 'Website Domain')}</label>
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
              const updated = [...currentList, {
                name,
                domain,
                relationship: 'direct_competitor',
                relationship_source: 'user',
                relationship_confidence: 'confirmed',
                relationship_review_required: false,
                benchmark_eligible: true,
              }];
              await workspace.patchConfig(projectId, { competitors: updated });
              toast.success(t('competitors.added_success', {}, 'Competitor added'));
              ctx.navigate('#/competitors');
              return true;
            } catch (err) {
              toast.error(tError(err));
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
          toast.error(tError(err));
        }
      });
    });
  },
};
