/**
 * 外部集成 (Integrations)
 */

import { integrations } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}K`;
  return number.toLocaleString();
}

function formatDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

export default {
  render: async (ctx) => {
    let settings = { providers: {} };
    let trafficResponse = null;
    const activeProjectId = ctx.activeProjectId;
    try {
      [settings, trafficResponse] = await Promise.all([
        integrations.list().catch(() => ({ providers: {} })),
        activeProjectId ? integrations.getProjectTraffic(activeProjectId).catch(() => null) : Promise.resolve(null),
      ]);
    } catch (e) {}

    const tabapiConfig = settings?.providers?.tabapi || {};
    const semrushConfig = settings?.providers?.semrush || {};
    const gscConfig = settings?.providers?.search_console || {};
    const traffic = trafficResponse?.traffic || null;

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('integrations.title', {}, 'External SEO & Data Integrations')}</h1>
            <p class="view-desc">
              ${t('integrations.desc', {}, 'Connect TabAPI (AITDK), Google Search Console, and Semrush to cross-reference web traffic and search queries with generative AI visibility.')}
            </p>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(340px, 1fr));gap:var(--sp-6);">
          <!-- TabAPI (AITDK Traffic Intelligence) -->
          <div class="card" style="gap:var(--sp-4);display:flex;flex-direction:column;justify-content:space-between;border-color:${tabapiConfig.configured ? 'var(--accent)' : 'var(--divider)'};">
            <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;align-items:center;gap:var(--sp-2);">
                  <strong style="font-size:var(--fs-4);">TabAPI · AITDK</strong>
                  ${tabapiConfig.configured ? `<span class="tag tag-success" style="font-size:10px;">Connected (${tabapiConfig.masked || 'Active'})</span>` : `<span class="tag tag-dim" style="font-size:10px;">API Key · BYOK</span>`}
                </div>
                <span class="tag tag-neutral">Traffic Intelligence</span>
              </div>
              <p style="color:var(--muted);font-size:var(--fs-2);margin:0;line-height:1.5;">
                ${t('integrations.tabapi_desc', {}, 'Automate domain monthly traffic tracking, global rankings, bounce rates, and traffic sources powered by TabAPI (aitdk.com).')}
              </p>
              <div style="font-size:var(--fs-1);color:var(--faint);">
                <span>Need a key? </span>
                <a href="https://tabapi.com" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:underline;">Get API Key on tabapi.com ↗</a>
              </div>
            </div>

            <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;margin-top:var(--sp-3);">
              <button type="button" class="btn btn-primary btn-sm btn-connect-tabapi">
                ${tabapiConfig.configured ? t('integrations.reconfigure', {}, 'Update Key') : t('integrations.connect_tabapi', {}, 'Configure TabAPI Key')}
              </button>
              ${tabapiConfig.configured ? `
                <button type="button" class="btn btn-ghost btn-sm btn-disconnect" data-provider="tabapi" style="color:var(--bad);">
                  ${t('common.disconnect', {}, 'Disconnect')}
                </button>
              ` : ''}
            </div>
          </div>

          <!-- Google Search Console -->
          <div class="card" style="gap:var(--sp-4);display:flex;flex-direction:column;justify-content:space-between;">
            <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;align-items:center;gap:var(--sp-2);">
                  <strong style="font-size:var(--fs-4);">Google Search Console</strong>
                  ${gscConfig.configured ? `<span class="tag tag-success" style="font-size:10px;">Connected</span>` : `<span class="tag tag-dim" style="font-size:10px;">OAuth 2.0</span>`}
                </div>
                <span class="tag tag-neutral">Search Analytics</span>
              </div>
              <p style="color:var(--muted);font-size:var(--fs-2);margin:0;line-height:1.5;">
                Import organic search impressions, clicks, CTR, and ranking queries to discover high-value prompt topics.
              </p>
            </div>
            <div style="display:flex;align-items:center;gap:var(--sp-2);margin-top:var(--sp-3);">
              <button type="button" class="btn btn-secondary btn-sm btn-connect-gsc" ${activeProjectId ? '' : 'disabled'}>
                ${t('integrations.connect_gsc', {}, 'Authorize Search Console')}
              </button>
              ${gscConfig.configured ? `
                <button type="button" class="btn btn-ghost btn-sm btn-disconnect" data-provider="search_console" style="color:var(--bad);">
                  ${t('common.disconnect', {}, 'Disconnect')}
                </button>
              ` : ''}
            </div>
          </div>

          <!-- Semrush -->
          <div class="card" style="gap:var(--sp-4);display:flex;flex-direction:column;justify-content:space-between;">
            <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;align-items:center;gap:var(--sp-2);">
                  <strong style="font-size:var(--fs-4);">Semrush API</strong>
                  ${semrushConfig.configured ? `<span class="tag tag-success" style="font-size:10px;">Connected (${semrushConfig.masked || 'Active'})</span>` : `<span class="tag tag-dim" style="font-size:10px;">API Key</span>`}
                </div>
                <span class="tag tag-neutral">Competitor Matrix</span>
              </div>
              <p style="color:var(--muted);font-size:var(--fs-2);margin:0;line-height:1.5;">
                Sync competitor organic keyword overlap, domain authority metrics, and organic search CPC estimates.
              </p>
            </div>
            <div style="display:flex;align-items:center;gap:var(--sp-2);margin-top:var(--sp-3);">
              <button type="button" class="btn btn-secondary btn-sm btn-connect-semrush">
                ${semrushConfig.configured ? t('integrations.reconfigure', {}, 'Update Key') : t('integrations.connect_semrush', {}, 'Configure Semrush Key')}
              </button>
              ${semrushConfig.configured ? `
                <button type="button" class="btn btn-ghost btn-sm btn-disconnect" data-provider="semrush" style="color:var(--bad);">
                  ${t('common.disconnect', {}, 'Disconnect')}
                </button>
              ` : ''}
            </div>
          </div>
        </div>

        <section aria-labelledby="traffic-snapshot-title" style="display:flex;flex-direction:column;gap:var(--sp-4);padding-top:var(--sp-2);border-top:1px solid var(--line);">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;">
            <div>
              <h2 id="traffic-snapshot-title" style="font-size:var(--fs-5);font-weight:700;margin:0;">${t('integrations.traffic_title', {}, 'Domain Traffic Snapshot')}</h2>
              <p style="font-size:var(--fs-2);color:var(--muted);margin:2px 0 0;">${t('integrations.traffic_desc', {}, 'Third-party traffic estimates for the active project, provided by TabAPI / AITDK.')}</p>
            </div>
            ${tabapiConfig.configured && activeProjectId ? `
              <button type="button" class="btn btn-secondary btn-sm btn-sync-tabapi" data-project="${activeProjectId}">
                ${t('integrations.sync_now', {}, 'Sync Traffic Now')}
              </button>
            ` : ''}
          </div>

          ${traffic ? `
            <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;">
              <span class="tag tag-success">TabAPI · Synced</span>
              <span class="tag tag-dim num">${new Date(traffic.synced_at).toLocaleString()}</span>
              <span style="font-size:var(--fs-1);color:var(--muted);">Estimates only · not used in AI citation scoring</span>
            </div>
            <div class="kpi-grid">
              <div class="kpi-card">
                <span class="kpi-label">Monthly Visits</span>
                <strong class="kpi-val num">${formatNumber(traffic.metrics?.monthly_visits)}</strong>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Global Rank</span>
                <strong class="kpi-val num">${traffic.metrics?.global_rank ? `#${Number(traffic.metrics.global_rank).toLocaleString()}` : '—'}</strong>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Bounce Rate</span>
                <strong class="kpi-val num">${Number.isFinite(Number(traffic.metrics?.bounce_rate)) ? `${Math.round(Number(traffic.metrics.bounce_rate) * 100)}%` : '—'}</strong>
              </div>
              <div class="kpi-card">
                <span class="kpi-label">Average Visit</span>
                <strong class="kpi-val num">${formatDuration(traffic.metrics?.dwell_time)}</strong>
              </div>
            </div>
            ${traffic.traffic_sources && Object.keys(traffic.traffic_sources).length ? `
              <div style="display:flex;flex-direction:column;gap:var(--sp-3);padding-top:var(--sp-2);">
                <h3 style="font-size:var(--fs-3);font-weight:600;margin:0;">Traffic Channel Mix</h3>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-4);">
                  ${Object.entries(traffic.traffic_sources).map(([source, value]) => {
                    const percent = Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
                    return `
                      <div style="display:flex;flex-direction:column;gap:6px;">
                        <div style="display:flex;justify-content:space-between;gap:var(--sp-2);font-size:var(--fs-2);">
                          <span style="color:var(--muted);text-transform:capitalize;">${escapeHtml(String(source).replaceAll('_', ' '))}</span>
                          <span class="num">${percent}%</span>
                        </div>
                        <div style="height:6px;background:var(--line);overflow:hidden;border-radius:3px;" role="progressbar" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100">
                          <div style="height:100%;width:${percent}%;background:var(--accent);"></div>
                        </div>
                      </div>
                    `;
                  }).join('')}
                </div>
              </div>
            ` : ''}
          ` : `
            <div class="empty" style="border:1px dashed var(--divider);">
              <strong>${tabapiConfig.configured ? 'No traffic snapshot yet' : 'TabAPI is not connected'}</strong>
              <p style="max-width:52ch;margin:0 auto;color:var(--muted);">${tabapiConfig.configured ? 'Sync the active project to load its latest domain traffic estimate.' : 'Configure a TabAPI key above to enable third-party domain traffic estimates.'}</p>
            </div>
          `}
        </section>
      </div>
    `;
  },

  mounted: (ctx) => {
    const refresh = () => window.dispatchEvent(new HashChangeEvent('hashchange'));

    // TabAPI Modal
    document.querySelector('.btn-connect-tabapi')?.addEventListener('click', () => {
      openModal({
        title: 'Configure TabAPI (AITDK Traffic Intelligence)',
        content: `
          <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Enter your TabAPI Bearer Token to pull live monthly website visits, ranking estimates, and channel breakdowns.
            </p>
            <div class="field" style="margin:0;">
              <label>TabAPI Bearer Token *</label>
              <input type="password" id="tabapi-key-input" class="input" placeholder="tab_live_••••••••••••••••" autofocus>
              <span class="field-hint">You can find or create API tokens at <a href="https://tabapi.com" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">tabapi.com/dashboard</a>.</span>
            </div>
          </div>
        `,
        confirmText: 'Save & Encrypt Key',
        onConfirm: async () => {
          const input = document.getElementById('tabapi-key-input') || document.querySelector('#tabapi-key-input');
          const api_key = input?.value?.trim();
          if (!api_key) {
            toast.error('Please enter a valid TabAPI key');
            return false;
          }

          try {
            await integrations.saveTabapi({ api_key });
            toast.success('TabAPI key encrypted and saved');
            refresh();
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to save TabAPI key'));
            return false;
          }
        },
      });
    });

    // TabAPI Sync Now
    document.querySelector('.btn-sync-tabapi')?.addEventListener('click', async (e) => {
      const projectId = e.currentTarget.dataset.project;
      if (!projectId) return;
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Syncing...';
      try {
        await integrations.sync(projectId, 'tabapi');
        toast.success('TabAPI traffic sync task queued');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to queue TabAPI sync'));
      } finally {
        btn.disabled = false;
        btn.textContent = t('integrations.sync_now', {}, 'Sync Traffic Now');
      }
    });

    // Semrush Modal
    document.querySelector('.btn-connect-semrush')?.addEventListener('click', () => {
      openModal({
        title: 'Configure Semrush API',
        content: `
          <div class="field" style="margin:0;">
            <label>Semrush API Key *</label>
            <input type="password" id="semrush-key-input" class="input" placeholder="••••••••••••••••" autofocus>
          </div>
        `,
        confirmText: 'Save Key',
        onConfirm: async () => {
          const input = document.getElementById('semrush-key-input') || document.querySelector('#semrush-key-input');
          const api_key = input?.value?.trim();
          if (!api_key) return false;

          try {
            await integrations.saveSemrush({ api_key });
            toast.success('Semrush API key saved');
            refresh();
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to save Semrush key'));
            return false;
          }
        },
      });
    });

    // Disconnect Provider
    document.querySelectorAll('.btn-disconnect').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const provider = e.currentTarget.dataset.provider;
        if (!confirm(`Are you sure you want to disconnect ${provider}?`)) return;
        try {
          await integrations.delete(provider);
          toast.success(`${provider} disconnected`);
          refresh();
        } catch (err) {
          toast.error(t(err.error, {}, 'Failed to disconnect integration'));
        }
      });
    });
  },
};
