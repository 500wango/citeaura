/**
 *  (Report & Deliveries)
 */

import { projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { gradeBadge, statusPill } from '../components/badge.js';
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

    const overallGrade = report && report.grade;
    const mentionRate = report && report.mention_rate !== null && report.mention_rate !== undefined ? `${Math.round(report.mention_rate * 100)}%` : 'Unmeasured';
    const quality = report && report.report_quality;
    const confidence = quality && quality.confidence;
    const confidenceLabel = confidence && confidence.label ? confidence.label : 'No baseline';
    const trend = (quality && quality.measurement_quality && quality.measurement_quality.trend) || {};
    const trendNote = trend.status === 'noteworthy'
      ? `${trend.label || 'Trend'} ${trend.delta_pp != null ? `(${trend.delta_pp} pp)` : ''}`
      : (trend.label || 'Single-round observation. Two comparable sample periods are required before treating a change as a trend.');
    const assetTotals = deliveries.reduce((totals, item) => {
      const summary = item && item.asset_summary ? item.asset_summary : {};
      totals.ready += Number(summary.ready || 0);
      totals.needs_review += Number(summary.needs_review || 0);
      totals.template += Number(summary.template || 0);
      return totals;
    }, { ready: 0, needs_review: 0, template: 0 });

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('report.title', {}, 'Client Delivery Packs')}</h1>
            <p class="view-desc">
              ${t('report.desc', {}, 'The first-run ZIP is the diagnostic final pack. Send documents 01–06 to the client. Templates and unmeasured visibility stay disclosed as implementation backlog — they do not block this pack.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-generate-delivery" class="btn btn-primary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              <span>${t('report.generate_pack_btn', {}, 'Build New Delivery Pack')}</span>
            </button>
          </div>
        </div>

        <!-- Deliverables Overview -->
        <div class="card" style="gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:var(--sp-3);">
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              ${overallGrade ? gradeBadge(overallGrade) : '<span class="tag tag-dim">Unmeasured</span>'}
              ${statusPill(confidence && confidence.sufficient ? 'good' : 'warning', confidenceLabel)}
              <div>
                <strong style="font-size:var(--fs-4);">${t('report.exec_summary', {}, 'Pack snapshot')}</strong>
                <div style="color:var(--muted);font-size:var(--fs-2);">${trendNote} · <a href="#/engines">Open visibility matrix</a></div>
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
              <strong style="font-size:var(--fs-2);margin-top:2px;">Action Tickets</strong>
              <span style="font-size:11px;color:var(--muted);margin-top:2px;">Impact × Effort roadmap</span>
            </div>
            <div class="card" style="background:var(--page);border-radius:var(--r-md);padding:var(--sp-3);">
              <span class="kicker">03 · Assets</span>
              <strong style="font-size:var(--fs-2);margin-top:2px;">Asset readiness</strong>
              <span style="font-size:11px;color:var(--muted);margin-top:2px;">${assetTotals.ready} ready · ${assetTotals.needs_review} review · ${assetTotals.template} templates</span>
            </div>
          </div>
        </div>

        <!-- Historical Delivery Packages List -->
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
                      const customerReady = d.readiness === 'customer_ready';
                      const reviewRequired = d.readiness === 'review_required';
                      const implementationReady = Boolean(d.implementation_ready);
                      const diagnosticReady = d.diagnostic_ready !== false && customerReady;
                      const statusLabel = implementationReady
                        ? t('report.status_implementation', {}, 'Implementation pack ready')
                        : diagnosticReady
                          ? t('report.status_diagnostic', {}, 'Diagnostic pack ready')
                          : reviewRequired
                            ? t('report.status_review', {}, 'Review package')
                            : t('report.status_unknown', {}, 'Readiness unavailable');
                      const downloadLabel = implementationReady
                        ? 'Download implementation ZIP'
                        : customerReady
                          ? 'Download diagnostic ZIP'
                          : 'Download review ZIP';
                      const backlogNote = !implementationReady && Array.isArray(d.implementation_backlog) && d.implementation_backlog.length
                        ? `${Number((d.asset_summary || {}).template || 0)} outlines remain implementation backlog`
                        : `${Number((d.asset_summary || {}).ready || 0)} ready · ${Number((d.asset_summary || {}).needs_review || 0)} review · ${Number((d.asset_summary || {}).template || 0)} templates`;
                      return `
                      <tr>
                        <td>
                          <span class="num" style="font-weight:700;font-size:var(--fs-3);">${dateStr}</span>
                        </td>
                        <td>
                          <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;">
                            ${statusPill(customerReady ? 'good' : 'warning', statusLabel)}
                            <span style="font-size:var(--fs-2);color:var(--muted);">${backlogNote}</span>
                          </div>
                        </td>
                        <td style="text-align:right;">
                          <a href="${dlUrl}" class="btn btn-secondary btn-sm" download title="${reviewRequired ? 'Contains assets that require review before publishing.' : implementationReady ? 'Diagnostic documents and publishable assets passed the current checks.' : customerReady ? 'Diagnostic final pack. Implementation outlines stay classified and do not block sending this ZIP.' : 'Readiness could not be confirmed.'}" aria-label="${downloadLabel}">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            <span>${t(implementationReady ? 'report.download_implementation_zip' : customerReady ? 'report.download_diagnostic_zip' : 'report.download_review_zip', {}, downloadLabel)}</span>
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
          const res = await projects.triggerDeliver(projectId);
          toast.success(t('report.deliver_queued', {}, 'Delivery pack build job queued!'));
          ctx.pollActiveJobs();
          if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'deliver');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to start delivery pack compilation'));
        } finally {
          generateBtn.disabled = false;
        }
      });
    }
  },
};
