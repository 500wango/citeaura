/**
 * 引用来源与渠道分析视图 (Channels & Citation Sources)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
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

    const channels = (report && report.channels) || [];

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('channels.title', {}, 'AI Citation Sources & Media Channels')}</h1>
            <p class="view-desc">
              ${t('channels.desc', {}, 'Identify the third-party platforms, authoritative directories, and review domains most frequently cited by LLMs during web retrieval.')}
            </p>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('channels.top_domains', {}, 'Top Cited Domain Authorities')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${channels.length} domains</span>
          </div>

          ${
            channels.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>${t('channels.col_domain', {}, 'Source Domain')}</th>
                    <th>${t('channels.col_category', {}, 'Channel Type')}</th>
                    <th style="text-align:right;">${t('channels.col_citations', {}, 'Citation Mentions')}</th>
                    <th>${t('channels.col_opportunity', {}, 'Outreach Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${channels
                    .map(
                      (ch, idx) => `
                    <tr>
                      <td class="num" style="color:var(--muted);">${idx + 1}</td>
                      <td>
                        <span class="num" style="font-weight:600;font-size:var(--fs-3);color:var(--ink);">${ch.domain || ch.name}</span>
                      </td>
                      <td>
                        <span class="tag tag-neutral">${ch.type || 'Directory / Media'}</span>
                      </td>
                      <td data-num style="font-weight:700;">
                        ${ch.count || 1}
                      </td>
                      <td>
                        <a href="#/outreach" class="btn btn-ghost btn-sm">
                          ${t('channels.create_outreach', {}, 'Draft Outreach')} →
                        </a>
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
            <div style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
              <p>${t('channels.no_citations_yet', {}, 'No search-grounded citation domains captured in current sample set. Citation mapping updates automatically with web-retrieval sampling runs.')}</p>
            </div>
          `
          }
        </div>
      </div>
    `;
  },
};
