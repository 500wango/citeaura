/**
 *  GEO  (Site Audit)
 */

import { projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { gradeBadge } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderFindings(page) {
  const findings = Array.isArray(page.findings) ? page.findings : [];
  if (findings.length) {
    return findings.map((finding) => `
      <span class="tag pill-warn" title="${escapeHtml(finding.detail || finding.title)}">
        <span class="num">${escapeHtml(finding.severity || 'P2')}</span>
        ${escapeHtml(finding.title || finding.code)}
      </span>
    `).join('');
  }
  if (page.evaluation_status === 'excluded') {
    return `<span class="tag tag-dim">${escapeHtml(page.evaluation_note || 'Excluded from public-content scoring')}</span>`;
  }
  if (page.evaluation_status === 'not_evaluated') {
    return '<span class="tag tag-dim">Insufficient crawl evidence</span>';
  }
  return '<span class="tag tag-dim">No applicable gaps detected</span>';
}

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
    const usesApplicableScore = Number(audit.presentation_version || 0) >= 1;
    const avgScore = usesApplicableScore
      ? (audit.applicable_avg_score ?? null)
      : (audit.avg_score ?? audit.score ?? null);
    const grade = usesApplicableScore ? audit.applicable_grade : (report && report.grade);
    const scoreUnavailableLabel = usesApplicableScore ? 'Not scored' : 'Unmeasured';
    const summary = audit.check_summary || {};
    const siteFindings = Array.isArray(audit.site_findings) ? audit.site_findings : [];

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
            <span class="kicker">${t('siteaudit.overall_score', {}, 'Applicable Technical Score')}</span>
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              ${grade ? gradeBadge(grade) : `<span class="tag tag-dim">${scoreUnavailableLabel}</span>`}
              <span class="num" style="font-size:var(--fs-7);font-weight:700;">${avgScore ?? scoreUnavailableLabel}</span>
              ${avgScore === null ? '' : '<span style="color:var(--muted);font-size:var(--fs-2);">/ 100</span>'}
            </div>
          </div>
          <div class="card" style="gap:var(--sp-2);">
            <span class="kicker">${t('siteaudit.crawled_pages', {}, 'Audited Pages')}</span>
            <span class="num" style="font-size:var(--fs-7);font-weight:700;">${pages.length}</span>
            <span style="color:var(--muted);font-size:11px;">${summary.excluded_pages || 0} utility pages excluded from content scoring</span>
          </div>
          <div class="card" style="gap:var(--sp-2);">
            <span class="kicker">Applicable Checks</span>
            <span class="num" style="font-size:var(--fs-7);font-weight:700;">${summary.passed || 0} / ${summary.evaluated || 0}</span>
            <span style="color:var(--muted);font-size:11px;">${summary.not_evaluated || 0} not evaluated / ${summary.not_applicable || 0} not applicable</span>
          </div>
        </div>

        ${siteFindings.length ? `
          <div class="card" style="gap:var(--sp-3);">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">Site-level Findings</h3>
              <span class="tag tag-dim">${siteFindings.length} detected</span>
            </div>
            <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">
              ${siteFindings.map((finding) => `
                <span class="tag pill-warn" title="${escapeHtml(finding.detail || finding.title)}">
                  <span class="num">${escapeHtml(finding.severity || 'P2')}</span>
                  ${escapeHtml(finding.title || finding.code)}
                </span>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <!-- Page Audit Detailed Breakdown -->
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('siteaudit.pages_table_title', {}, 'Page-level Applicable Audit')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${pages.length} pages</span>
          </div>

          ${
            pages.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table" style="min-width:920px;table-layout:fixed;">
                <thead>
                  <tr>
                    <th style="width:31%;">${t('siteaudit.col_url', {}, 'Page URL')}</th>
                    <th style="width:10%;">${t('siteaudit.col_grade', {}, 'Grade')}</th>
                    <th style="width:10%;text-align:right;">${t('siteaudit.col_score', {}, 'Score')}</th>
                    <th>${t('siteaudit.col_issues', {}, 'Applicable Findings')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${pages
                    .map(
                      (p) => `
                    <tr>
                      <td>
                        <div class="num" style="font-weight:600;color:var(--ink);overflow-wrap:anywhere;">${escapeHtml(p.url || p.path || '/')}</div>
                        <div style="display:flex;align-items:center;gap:var(--sp-2);margin-top:6px;flex-wrap:wrap;">
                          <span class="tag tag-dim">${escapeHtml(p.role?.label || 'General content page')}</span>
                          <span style="font-size:11px;color:var(--muted);">${p.check_summary?.evaluated || 0} checks / ${(p.check_summary?.not_applicable || 0) + (p.check_summary?.not_evaluated || 0)} skipped</span>
                        </div>
                      </td>
                      <td>${p.applicable_grade ? gradeBadge(p.applicable_grade) : '<span class="tag tag-dim">Not scored</span>'}</td>
                      <td data-num style="font-weight:700;color:var(--ink);">${p.applicable_score ?? 'Not scored'}</td>
                      <td>
                        <div style="display:flex;gap:4px;flex-wrap:wrap;">
                          ${renderFindings(p)}
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
              ${renderEmpty({ title: 'No site audit data', description: 'Run a site audit to measure crawlability and extraction structure.' })}
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
