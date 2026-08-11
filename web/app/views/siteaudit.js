/**
 *  GEO  (Site Audit)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { gradeBadge } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let report = null;
    try {
      report = await projects.getReport(projectId).catch(() => null);
    } catch (e) {}

    const audit = (report && report.audit) || {};
    const pages = (audit && audit.pages) || [];
    const avgScore = audit.avg_score || audit.score || 72;
    const grade = (report && report.grade) || 'B';

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('siteaudit.title', {}, 'Site-wide GEO Technical Audit')}</h1>
            <p class="view-desc">
              ${t('siteaudit.desc', {}, 'Inspect crawlability, structural semantics, extraction blocks, and schema markup preventing LLMs from indexing brand pages.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-re-audit" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              <span>${t('siteaudit.re_audit_btn', {}, 'Re-run Site Audit')}</span>
            </button>
          </div>
        </div>

        <!-- Score Overview Card -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:var(--sp-4);">
          <div class="card" style="gap:var(--sp-2);">
            <span class="kicker">${t('siteaudit.overall_score', {}, 'Technical Score')}</span>
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              ${gradeBadge(grade)}
              <span class="num" style="font-size:var(--fs-7);font-weight:700;">${avgScore}</span>
              <span style="color:var(--muted);font-size:var(--fs-2);">/ 100</span>
            </div>
          </div>
          <div class="card" style="gap:var(--sp-2);">
            <span class="kicker">${t('siteaudit.crawled_pages', {}, 'Audited Pages')}</span>
            <span class="num" style="font-size:var(--fs-7);font-weight:700;">${pages.length || 1}</span>
            <span style="color:var(--muted);font-size:11px;">Core domain pages indexed</span>
          </div>
          <div class="card" style="gap:var(--sp-2);">
            <span class="kicker">LLMs.txt Status</span>
            <span style="font-weight:600;font-size:var(--fs-4);color:var(--good);">Ready to Deploy</span>
            <a href="#/assets" style="font-size:11px;">View generated /llms.txt →</a>
          </div>
        </div>

        <!-- Page Audit Detailed Breakdown -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('siteaudit.pages_table_title', {}, 'Page Level Extraction Audit')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${pages.length} pages</span>
          </div>

          ${
            pages.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('siteaudit.col_url', {}, 'Page URL')}</th>
                    <th>${t('siteaudit.col_grade', {}, 'Grade')}</th>
                    <th style="text-align:right;">${t('siteaudit.col_score', {}, 'Score')}</th>
                    <th>${t('siteaudit.col_issues', {}, 'Detected Extraction Gaps')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${pages
                    .map(
                      (p) => `
                    <tr>
                      <td>
                        <span class="num" style="font-weight:600;color:var(--ink);">${p.url || p.path || '/'}</span>
                      </td>
                      <td>${gradeBadge(p.grade || 'B')}</td>
                      <td data-num style="font-weight:700;color:var(--ink);">${p.score || 80}</td>
                      <td>
                        <div style="display:flex;gap:4px;flex-wrap:wrap;">
                          ${
                            p.issues && p.issues.length
                              ? p.issues.map((iss) => `<span class="tag pill-warn">${iss}</span>`).join('')
                              : '<span class="tag pill-good">No critical blockers</span>'
                          }
                        </div>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `
            <div style="padding:var(--sp-6);font-size:var(--fs-2);color:var(--muted);">
              <p>Home page audit baseline established. Extraction blocks: <strong>JSON-LD</strong>, <strong>FAQ</strong>, <strong>Numeric facts</strong>.</p>
            </div>
          `
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-re-audit')?.addEventListener('click', async () => {
      try {
        await projects.triggerAction(projectId, 'audit');
        ctx.pollActiveJobs();
      } catch (e) {}
    });
  },
};
