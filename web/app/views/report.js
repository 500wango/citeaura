/**
 * 交付报告与客户包导出视图 (Report & Deliveries)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { gradeBadge } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let report = null;
    let deliveries = [];

    try {
      [report, deliveries] = await Promise.all([
        projects.getReport(projectId).catch(() => null),
        projects.getDeliveries(projectId).catch(() => []),
      ]);
    } catch (err) {
      console.error('Failed to load report data:', err);
    }

    const overallGrade = (report && report.grade) || 'C';
    const mentionRate = report && report.mention_rate !== undefined ? `${Math.round(report.mention_rate * 100)}%` : '—';

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('report.title', {}, 'Deliverables & Client Delivery Packs')}</h1>
            <p class="view-desc">
              ${t('report.desc', {}, 'Export audit decks, action matrices, ticket logs, before/after comparisons, and ready-to-deploy structured assets.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-generate-delivery" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              <span>${t('report.generate_pack_btn', {}, 'Build New Delivery Pack')}</span>
            </button>
          </div>
        </div>

        <!-- 交付大盘速览 -->
        <div class="card" style="gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:var(--sp-3);">
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              ${gradeBadge(overallGrade)}
              <div>
                <strong style="font-size:var(--fs-4);">${t('report.exec_summary', {}, 'Executive Audit Summary')}</strong>
                <div style="color:var(--muted);font-size:var(--fs-2);">${t('report.verified_baseline', {}, 'Deterministic GEO visibility score baseline')}</div>
              </div>
            </div>
            <div class="num" style="font-size:var(--fs-7);font-weight:700;color:var(--ink);">
              ${mentionRate}
            </div>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:var(--sp-4);">
            <div class="card" style="background:var(--page);border-radius:var(--r-md);padding:var(--sp-3);">
              <span class="kicker">01 · Audit</span>
              <strong style="font-size:var(--fs-2);margin-top:2px;">Full GEO Audit Deck</strong>
              <span style="font-size:11px;color:var(--muted);margin-top:2px;">Crawlability & model blockers</span>
            </div>
            <div class="card" style="background:var(--page);border-radius:var(--r-md);padding:var(--sp-3);">
              <span class="kicker">02 · Action</span>
              <strong style="font-size:var(--fs-2);margin-top:2px;">13 Action Tickets</strong>
              <span style="font-size:11px;color:var(--muted);margin-top:2px;">Impact × Effort roadmap</span>
            </div>
            <div class="card" style="background:var(--page);border-radius:var(--r-md);padding:var(--sp-3);">
              <span class="kicker">03 · Assets</span>
              <strong style="font-size:var(--fs-2);margin-top:2px;">Deployable Assets</strong>
              <span style="font-size:11px;color:var(--muted);margin-top:2px;">JSON-LD, /llms.txt, blocks</span>
            </div>
          </div>
        </div>

        <!-- 历史交付包列表 -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('report.history_title', {}, 'Delivery Pack Archives')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${deliveries.length} ${t('common.packs_total', {}, 'packages')}</span>
          </div>

          ${
            deliveries && deliveries.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('report.col_date', {}, 'Generation Date')}</th>
                    <th>${t('report.col_contents', {}, 'Package Contents')}</th>
                    <th style="text-align:right;">${t('common.download', {}, 'Download')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${deliveries
                    .map((d) => {
                      const dateStr = typeof d === 'string' ? d : d.date || d.name || 'Archive';
                      const dlUrl = projects.getDeliveryDownloadUrl(projectId, dateStr);
                      return `
                      <tr>
                        <td>
                          <span class="num" style="font-weight:700;font-size:var(--fs-3);">${dateStr}</span>
                        </td>
                        <td>
                          <span style="font-size:var(--fs-2);color:var(--muted);">index.html, 01~06 markdown documentation, and /assets zip</span>
                        </td>
                        <td style="text-align:right;">
                          <a href="${dlUrl}" class="btn btn-secondary btn-sm" download>
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            <span>${t('report.download_zip', {}, 'Download ZIP')}</span>
                          </a>
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
                  title: t('report.no_deliveries', {}, 'No Delivery Packs Built Yet'),
                  description: t('report.no_deliveries_desc', {}, 'Click the button above to compile full audit decks and deployment assets into a standalone ZIP pack.'),
                  actionText: t('report.generate_pack_btn', {}, 'Build New Delivery Pack'),
                  onAction: () => document.getElementById('btn-generate-delivery')?.click(),
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

    const generateBtn = document.getElementById('btn-generate-delivery');
    if (generateBtn) {
      generateBtn.addEventListener('click', async () => {
        generateBtn.disabled = true;
        try {
          await projects.triggerDeliver(projectId);
          toast.success(t('report.deliver_queued', {}, 'Delivery pack build job queued!'));
          ctx.pollActiveJobs();
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to start delivery pack compilation'));
        } finally {
          generateBtn.disabled = false;
        }
      });
    }
  },
};
