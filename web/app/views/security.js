/**
 *  (Security & SSO)
 */

import { sso } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    let ssoConfig = {};
    let auditEvents = [];
    try {
      [ssoConfig, auditEvents] = await Promise.all([
        sso.getConfig().catch(() => ({})),
        sso.getAuditEvents().catch(() => []),
      ]);
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('security.title', {}, 'Enterprise Security & OIDC SSO')}</h1>
            <p class="view-desc">
              ${t('security.desc', {}, 'Configure SAML/OIDC Single Sign-On and review tamper-evident organization access audit logs.')}
            </p>
          </div>
        </div>

        <!-- Compliance & Honesty Notice -->
        <div class="banner">
          <div>
            <strong style="display:block;">${t('security.compliance_title', {}, 'Security Controls & Certification Status')}</strong>
            <p style="margin:2px 0 0 0;font-size:12px;color:var(--muted);">
              ${t('security.soc2_notice', {}, 'Technical controls are ready; CiteAura is not SOC 2 certified.')}
            </p>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:minmax(0, 5fr) minmax(0, 7fr);gap:var(--sp-6);">
          <!-- OIDC SSO Settings -->
          <div class="card" style="gap:var(--sp-4);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('security.sso_config', {}, 'OIDC Identity Provider')}</h3>

            <div class="field" style="margin:0;">
              <label>OIDC Issuer URL *</label>
              <input type="url" id="sso-issuer" class="input" value="${ssoConfig.issuer_url || ''}" placeholder="https://login.microsoftonline.com/tenant-id/v2.0">
            </div>

            <div class="field" style="margin:0;">
              <label>Client ID *</label>
              <input type="text" id="sso-client-id" class="input" value="${ssoConfig.client_id || ''}" placeholder="00000000-0000-0000-0000-000000000000">
            </div>

            <div class="field" style="margin:0;">
              <label>${t('security.client_secret', {}, 'Client Secret')}</label>
              <input type="password" id="sso-client-secret" class="input" placeholder="••••••••••••••••">
            </div>

            <button type="button" id="btn-save-sso" class="btn btn-primary btn-sm" style="align-self:flex-start;">
              ${t('common.save_changes', {}, 'Save SSO Settings')}
            </button>
          </div>

          <!-- Audit Logs Table -->
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('security.audit_logs', {}, 'Access & Security Audit Events')}</h3>
            </div>

            ${
              auditEvents && auditEvents.length
                ? `
              <div class="tbl" style="overflow-x:auto;">
                <table class="table">
                  <thead>
                    <tr>
                      <th>${t('security.col_event', {}, 'Event')}</th>
                      <th>${t('security.col_actor', {}, 'Actor')}</th>
                      <th>IP</th>
                      <th>${t('security.col_time', {}, 'Time')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${auditEvents
                      .map(
                        (ev) => `
                      <tr>
                        <td><strong>${ev.event_type}</strong></td>
                        <td>${ev.actor_email || 'System'}</td>
                        <td class="num">${ev.ip_address || '—'}</td>
                        <td class="num">${new Date(ev.created_at).toLocaleTimeString()}</td>
                      </tr>
                    `
                      )
                      .join('')}
                  </tbody>
                </table>
              </div>
            `
                : `
              <div style="padding:var(--sp-6);font-size:var(--fs-2);color:var(--muted);text-align:center;">
                ${t('security.no_audit_events', {}, 'No security audit alerts logged in this session.')}
              </div>
            `
            }
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.getElementById('btn-save-sso')?.addEventListener('click', async () => {
      const issuer_url = document.getElementById('sso-issuer')?.value.trim();
      const client_id = document.getElementById('sso-client-id')?.value.trim();
      const client_secret = document.getElementById('sso-client-secret')?.value;

      try {
        await sso.saveConfig({ issuer_url, client_id, client_secret });
        toast.success('SSO configuration saved successfully');
      } catch (err) {
        toast.error(tError(err));
      }
    });
  },
};
