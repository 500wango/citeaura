/**
 *  (Overview)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderKpis } from '../components/kpi.js';
import { gradeBadge, samplingModeBadge, statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';
import { renderSkeleton } from '../components/skeleton.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `
        <div class="app-view-container">
          ${renderEmpty({
            title: t('overview.no_project_title', {}, 'No Brand Selected'),
            description: t('overview.no_project_desc', {}, 'Create your first brand project to begin measuring AI search visibility.'),
            actionText: t('overview.add_brand_btn', {}, 'Add Brand'),
            actionRoute: 'onboarding',
          })}
        </div>
      `;
    }

    let report = null;
    let project = null;
    let tickets = [];
    let jobs = [];

    try {
      [project, report, tickets, jobs] = await Promise.all([
        projects.get(projectId).catch(() => null),
        projects.getReport(projectId).catch(() => null),
        projects.getTickets(projectId).catch(() => []),
        projects.getJobs(projectId).catch(() => []),
      ]);
    } catch (err) {
      console.error('Failed to load overview data:', err);
    }

    if (!project) {
      return `<div class="app-view-container">${renderSkeleton({ rows: 6 })}</div>`;
    }

    const mentionRate = report && report.mention_rate !== undefined ? `${Math.round(report.mention_rate * 100)}%` : '—';
    const overallGrade = (report && report.grade) || 'C';
    const totalTickets = Array.isArray(tickets) ? tickets.length : 0;
    const doneTickets = Array.isArray(tickets) ? tickets.filter((t) => t.status === 'done').length : 0;
    const engines = (report && report.engines) || [];

    const kpiData = [
      { label: t('overview.kpi_mention_rate', {}, 'AI Mention Rate'), value: mentionRate, className: 'num' },
      { label: t('overview.kpi_grade', {}, 'Overall GEO Grade'), value: gradeBadge(overallGrade) },
      { label: t('overview.kpi_tickets', {}, 'Action Tickets'), value: `${doneTickets} / ${totalTickets}`, sub: `${totalTickets - doneTickets} pending` },
      { label: t('overview.kpi_engines', {}, 'Active Engines'), value: engines.length || '0', sub: 'Multi-model matrix' },
    ];

    return `
      <div class="app-view-container">
        <!-- View Header -->
        <div class="view-header">
          <div class="view-title-group">
            <div style="display:flex;align-items:center;gap:var(--sp-2);">
              <h1 class="view-title">${project.name || project.slug}</h1>
              ${gradeBadge(overallGrade)}
            </div>
            <div class="view-desc">
              <a href="${project.url}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:4px;color:var(--muted);text-decoration:none;">
                <span class="num">${project.url}</span>
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
              <span style="color:var(--faint);margin:0 var(--sp-2);">·</span>
              <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${t('common.market', {}, 'Market')}: ${project.market || 'Universal'}</span>
            </div>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-run-sample" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('overview.action_sample', {}, 'Run AI Sample')}</span>
            </button>
            <button type="button" id="btn-run-verify" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>${t('overview.action_verify', {}, 'Verify Changes')}</span>
            </button>
            <a href="#/report" class="btn btn-primary btn-sm">
              <span>${t('overview.action_deliver', {}, 'View Delivery Pack')}</span>
            </a>
          </div>
        </div>

        <!-- Key Metrics Bar -->
        ${renderKpis(kpiData)}

        <!-- Core Modules Column -->
        <div style="display:grid;grid-template-columns:minmax(0, 7fr) minmax(0, 5fr);gap:var(--sp-6);">
          <!-- Left: Model Mention Rates & Sampling Modes -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.engines_visibility', {}, 'AI Engine Visibility Matrix')}</h3>
              <a href="#/engines" style="font-size:var(--fs-2);">${t('common.view_all', {}, 'View all')} →</a>
            </div>

            ${
              engines.length
                ? `
              <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
                ${engines
                  .slice(0, 6)
                  .map(
                    (eng) => `
                  <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--sp-2) var(--sp-3);background:var(--page);border:1px solid var(--line);border-radius:var(--r-md);">
                    <div style="display:flex;flex-direction:column;gap:2px;">
                      <span style="font-weight:600;font-size:var(--fs-2);">${eng.engine_name || eng.engine_code}</span>
                      <div>${samplingModeBadge(eng.sampling_mode)}</div>
                    </div>
                    <div style="display:flex;align-items:center;gap:var(--sp-4);">
                      <div class="num" style="font-size:var(--fs-4);font-weight:700;color:var(--ink);">
                        ${eng.mention_rate !== undefined ? `${Math.round(eng.mention_rate * 100)}%` : '—'}
                      </div>
                    </div>
                  </div>
                `
                  )
                  .join('')}
              </div>
            `
                : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_engines_sampled', {}, 'No model sampling data recorded yet. Trigger a sample run to populate.')}</p>`
            }
          </div>

          <!-- Right: High-Priority Tickets -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.priority_tickets', {}, 'High-Impact Action Tickets')}</h3>
              <a href="#/plan" style="font-size:var(--fs-2);">${t('common.view_all', {}, 'View matrix')} →</a>
            </div>

            ${
              tickets && tickets.length
                ? `
              <div style="display:flex;flex-direction:column;gap:var(--sp-2);">
                ${tickets
                  .slice(0, 5)
                  .map((ticket) => {
                    const title = t(ticket.title, {}, ticket.title_en || ticket.title || ticket.name || ticket.id);
                    return `
                  <a class="ticket-item" href="#/plan" style="text-decoration:none;">
                    <div style="display:flex;align-items:center;justify-content:space-between;">
                      <span class="ticket-item-title">${title}</span>
                      ${statusPill(ticket.status)}
                    </div>
                    <div class="ticket-item-meta">
                      <span>Impact: <strong>${ticket.impact || 'High'}</strong></span>
                      <span>·</span>
                      <span>Effort: <strong>${ticket.effort || 'Low'}</strong></span>
                    </div>
                  </a>
                `;
                  })
                  .join('')}
              </div>
            `
                : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_tickets', {}, 'No action tickets generated yet.')}</p>`
            }
          </div>
        </div>

        <!-- Pipeline Jobs History -->
        <div class="card" style="gap:var(--sp-3);">
          <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.pipeline_activity', {}, 'Pipeline Job History')}</h3>
          ${
            jobs && jobs.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('common.action', {}, 'Action')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                    <th>${t('common.started_at', {}, 'Started')}</th>
                    <th>${t('common.duration', {}, 'Finished')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${jobs
                    .slice(0, 5)
                    .map(
                      (j) => `
                    <tr>
                      <td><span style="font-family:var(--font-mono);font-weight:600;">${j.action}</span></td>
                      <td>${statusPill(j.status)}</td>
                      <td class="num">${j.started_at ? new Date(j.started_at).toLocaleString() : '—'}</td>
                      <td class="num">${j.finished_at ? new Date(j.finished_at).toLocaleTimeString() : j.status === 'running' ? '<span class="spin"></span>' : '—'}</td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_jobs', {}, 'No job runs recorded yet.')}</p>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    const sampleBtn = document.getElementById('btn-run-sample');
    if (sampleBtn) {
      sampleBtn.addEventListener('click', async () => {
        sampleBtn.disabled = true;
        try {
          const res = await projects.triggerSample(projectId);
          toast.success(t('overview.sample_triggered', {}, 'AI sampling task queued!'));
          ctx.pollActiveJobs();
          if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'sample');
          }
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to trigger sampling'));
        } finally {
          sampleBtn.disabled = false;
        }
      });
    }

    const verifyBtn = document.getElementById('btn-run-verify');
    if (verifyBtn) {
      verifyBtn.addEventListener('click', async () => {
        verifyBtn.disabled = true;
        try {
          const res = await projects.triggerVerify(projectId);
          toast.success(t('overview.verify_triggered', {}, 'Verification task queued!'));
          ctx.pollActiveJobs();
          if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'verify');
          }
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to trigger verification'));
        } finally {
          verifyBtn.disabled = false;
        }
      });
    }
  },
};
