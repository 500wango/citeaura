/**
 * 渠道与信源分析 (Channels & Citation Sources)
 */

import { projects, integrations } from '../api.js';
import { t } from '../i18n.js';
import { renderEmpty } from '../components/empty.js';

function formatNumber(num) {
  if (num === null || num === undefined || isNaN(num)) return '—';
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return Number(num).toLocaleString();
}

function formatDuration(sec) {
  if (!sec || isNaN(sec)) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${s}s`;
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let report = null;
    let trafficRes = null;
    try {
      [report, trafficRes] = await Promise.all([
        projects.getReport(projectId).catch(() => null),
        integrations.getProjectTraffic(projectId).catch(() => null),
      ]);
    } catch (e) {}

    const channels = (report && report.channels) || [];
    const traffic = trafficRes?.traffic || null;
    const isConfigured = Boolean(trafficRes?.configured);

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('channels.title', {}, 'AI Citation Sources & Traffic Channels')}</h1>
            <p class="view-desc">
              ${t('channels.desc', {}, 'Track organic search citations, third-party media sources, and live domain traffic intelligence.')}
            </p>
          </div>
          <div class="view-actions">
            ${isConfigured ? `
              <button type="button" class="btn btn-secondary btn-sm btn-sync-traffic" data-project="${projectId}">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span>${t('integrations.sync_now', {}, 'Sync TabAPI Traffic')}</span>
              </button>
            ` : `
              <a href="#/integrations" class="btn btn-secondary btn-sm">
                <span>${t('integrations.connect_tabapi', {}, 'Connect TabAPI')}</span>
              </a>
            `}
          </div>
        </div>

        <!-- TabAPI Traffic Growth Intelligence Card -->
        <div class="card" style="margin-bottom:var(--sp-6);gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:var(--sp-3);">
            <div style="display:flex;align-items:center;gap:var(--sp-2);">
              <strong style="font-size:var(--fs-4);">TabAPI · Domain Traffic Intelligence</strong>
              ${traffic ? `<span class="tag tag-success" style="font-size:10px;">Synced ${new Date(traffic.synced_at).toLocaleDateString()}</span>` : (isConfigured ? `<span class="tag tag-dim" style="font-size:10px;">Ready to Sync</span>` : `<span class="tag tag-dim" style="font-size:10px;">Not Connected</span>`)}
            </div>
            <a href="https://tabapi.com" target="_blank" rel="noopener noreferrer" style="font-size:var(--fs-1);color:var(--muted);text-decoration:none;">
              Powered by TabAPI / AITDK ↗
            </a>
          </div>

          ${traffic ? `
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));gap:var(--sp-4);">
              <div style="padding:var(--sp-3);border-radius:var(--r-md);background:var(--page);border:1px solid var(--divider);">
                <span style="font-size:var(--fs-1);color:var(--muted);display:block;">Monthly Visits</span>
                <strong class="num" style="font-size:var(--fs-6);color:var(--ink);">${formatNumber(traffic.metrics?.monthly_visits)}</strong>
              </div>
              <div style="padding:var(--sp-3);border-radius:var(--r-md);background:var(--page);border:1px solid var(--divider);">
                <span style="font-size:var(--fs-1);color:var(--muted);display:block;">Global Rank</span>
                <strong class="num" style="font-size:var(--fs-6);color:var(--ink);">${traffic.metrics?.global_rank ? '#' + Number(traffic.metrics.global_rank).toLocaleString() : '—'}</strong>
              </div>
              <div style="padding:var(--sp-3);border-radius:var(--r-md);background:var(--page);border:1px solid var(--divider);">
                <span style="font-size:var(--fs-1);color:var(--muted);display:block;">Bounce Rate</span>
                <strong class="num" style="font-size:var(--fs-6);color:var(--ink);">${traffic.metrics?.bounce_rate ? Math.round(traffic.metrics.bounce_rate * 100) + '%' : '—'}</strong>
              </div>
              <div style="padding:var(--sp-3);border-radius:var(--r-md);background:var(--page);border:1px solid var(--divider);">
                <span style="font-size:var(--fs-1);color:var(--muted);display:block;">Avg Duration</span>
                <strong class="num" style="font-size:var(--fs-6);color:var(--ink);">${formatDuration(traffic.metrics?.dwell_time)}</strong>
              </div>
            </div>

            ${traffic.traffic_sources && Object.keys(traffic.traffic_sources).length ? `
              <div style="margin-top:var(--sp-2);">
                <span style="font-size:var(--fs-2);font-weight:600;color:var(--ink);display:block;margin-bottom:var(--sp-2);">Traffic Channel Breakdown</span>
                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:var(--sp-3);">
                  ${Object.entries(traffic.traffic_sources).map(([source, val]) => `
                    <div style="font-size:var(--fs-1);">
                      <div style="display:flex;justify-content:space-between;color:var(--muted);margin-bottom:2px;">
                        <span style="text-transform:capitalize;">${source.replace('_', ' ')}</span>
                        <span class="num">${Math.round(val * 100)}%</span>
                      </div>
                      <div style="height:4px;border-radius:2px;background:var(--line);overflow:hidden;">
                        <div style="height:100%;width:${Math.round(val * 100)}%;background:var(--accent);"></div>
                      </div>
                    </div>
                  `).join('')}
                </div>
              </div>
            ` : ''}
          ` : `
            <div style="padding:var(--sp-4);background:var(--page);border-radius:var(--r-md);display:flex;align-items:center;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;">
              <div>
                <p style="margin:0;font-size:var(--fs-2);color:var(--ink);font-weight:500;">
                  ${isConfigured ? 'TabAPI is connected. Click Sync to pull the latest monthly traffic report.' : 'Connect TabAPI to track live monthly domain visits, global rank, and channel traffic.'}
                </p>
                <p style="margin:2px 0 0 0;font-size:var(--fs-1);color:var(--muted);">
                  Get your free/developer API token at <a href="https://tabapi.com" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">tabapi.com</a>.
                </p>
              </div>
              ${isConfigured ? `
                <button type="button" class="btn btn-primary btn-sm btn-sync-traffic" data-project="${projectId}">
                  ${t('integrations.sync_now', {}, 'Sync Traffic Now')}
                </button>
              ` : `
                <a href="#/integrations" class="btn btn-primary btn-sm">
                  ${t('integrations.connect_tabapi', {}, 'Configure TabAPI Key')}
                </a>
              `}
            </div>
          `}
        </div>

        <!-- Citation Domains Table -->
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

  mounted: (ctx) => {
    document.querySelectorAll('.btn-sync-traffic').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const projectId = e.currentTarget.dataset.project;
        if (!projectId) return;
        const target = e.currentTarget;
        target.disabled = true;
        try {
          await integrations.sync(projectId, 'tabapi');
          const toastModule = await import('../components/toast.js');
          toastModule.toast.success('TabAPI traffic sync task enqueued');
        } catch (err) {
          const toastModule = await import('../components/toast.js');
          toastModule.toast.error(t(err.error, {}, err.detail || 'Failed to sync traffic'));
        } finally {
          target.disabled = false;
        }
      });
    });
  },
};

