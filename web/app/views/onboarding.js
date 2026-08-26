/**
 * Brand onboarding
 */

import { analytics, projects } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: () => {
    return `
      <div class="app-view-container">
        <div class="wizard-card">
          <div style="display:flex;flex-direction:column;gap:var(--sp-2);">
            <div class="kicker">${t('onboard.kicker', {}, 'Brand Setup')}</div>
            <h1 style="font-size:var(--fs-6);font-weight:700;letter-spacing:-0.02em;margin:0;">
              ${t('onboard.title', {}, 'Add Brand for AI Visibility Measurement')}
            </h1>
            <p style="color:var(--muted);font-size:var(--fs-3);line-height:1.6;margin:0;">
              ${t('onboard.desc', {}, 'Enter your official website URL. CiteAura will crawl core pages, extract facts, generate question sets, and initiate the initial diagnostic baseline.')}
            </p>
          </div>

          <form id="onboard-form" style="display:flex;flex-direction:column;gap:var(--sp-4);">
            <div class="field" style="margin:0;">
              <label for="ob-url">${t('onboard.url_label', {}, 'Official Website Domain / URL')} *</label>
              <input type="url" id="ob-url" class="input" placeholder="https://yourbrand.com" required autocomplete="url">
              <div class="field-hint">${t('onboard.url_hint', {}, 'Must be a publicly accessible website over HTTPS or HTTP.')}</div>
            </div>

            <div class="field" style="margin:0;">
              <label for="ob-name">${t('onboard.name_label', {}, 'Brand Display Name')} (${t('common.optional', {}, 'Optional')})</label>
              <input type="text" id="ob-name" class="input" placeholder="e.g. CiteAura">
            </div>

            <div id="ob-preflight" class="card" style="display:none;background:var(--page);padding:var(--sp-3);gap:var(--sp-2);"></div>

            <div class="card" style="background:var(--deep);padding:var(--sp-4);border-radius:var(--r-md);gap:var(--sp-3);">
              <div style="font-size:var(--fs-2);">
                <strong style="color:var(--ink);">${t('onboard.choose_result_title', {}, 'Choose your first result')}</strong>
                <div style="color:var(--muted);margin-top:4px;">${t('onboard.choose_result_desc', {}, 'Start with a technical diagnostic now, or add model access for a full AI baseline.')}</div>
              </div>
              <label class="onboard-mode-option" style="display:flex;align-items:flex-start;gap:var(--sp-3);padding:var(--sp-3);border:1px solid var(--brand);background:color-mix(in oklch, var(--brand) 8%, transparent);cursor:pointer;user-select:none;">
                <input type="radio" name="ob-mode" value="audit" checked style="margin-top:3px;">
                <div style="font-size:var(--fs-2);">
                  <strong style="color:var(--ink);">${t('onboard.mode_audit_title', {}, 'Audit only · recommended')}</strong>
                  <div style="color:var(--muted);margin-top:3px;">${t('onboard.mode_audit_desc', {}, 'Crawl, facts, tickets, and a diagnostic-ready report. No model API key or platform-pool funding required.')}</div>
                </div>
              </label>
              <label class="onboard-mode-option" style="display:flex;align-items:flex-start;gap:var(--sp-3);padding:var(--sp-3);border:1px solid var(--line);background:var(--page);cursor:pointer;user-select:none;">
                <input type="radio" name="ob-mode" value="baseline" style="margin-top:3px;">
                <div style="font-size:var(--fs-2);">
                  <strong style="color:var(--ink);">${t('onboard.mode_baseline_title', {}, 'Full AI baseline')}</strong>
                  <div style="color:var(--muted);margin-top:3px;">${t('onboard.mode_baseline_desc', {}, 'Run labeled AI sampling after preflight. Configure BYOK or an eligible platform pool before the job starts; provider charges remain visible to you.')}</div>
                </div>
              </label>
            </div>

            <div style="display:flex;align-items:center;justify-content:flex-end;gap:var(--sp-3);margin-top:var(--sp-4);padding-top:var(--sp-4);border-top:1px solid var(--line);">
              <a href="#/overview" class="btn btn-secondary">${t('common.cancel', {}, 'Cancel')}</a>
              <button type="submit" id="ob-submit" class="btn btn-primary">
                <span>${t('onboard.start_measurement', {}, 'Initialize Brand Pipeline')}</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const form = document.getElementById('onboard-form');
    if (!form) return;

    try {
      const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
      const paramDomain = urlParams.get('domain');
      const pendingDomain = paramDomain || sessionStorage.getItem('citeaura_pending_domain') || localStorage.getItem('citeaura_pending_domain');
      const pendingAudit = JSON.parse(sessionStorage.getItem('citeaura_pending_audit') || 'null');

      if (pendingDomain) {
        const clean = pendingDomain.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
        const urlInput = document.getElementById('ob-url');
        const nameInput = document.getElementById('ob-name');

        if (urlInput && !urlInput.value) {
          urlInput.value = `https://${clean}`;
        }
        if (nameInput && !nameInput.value) {
          const rawName = clean.split('.')[0];
          nameInput.value = rawName.charAt(0).toUpperCase() + rawName.slice(1);
        }
        toast.info(t('onboard.domain_loaded', {}, `Loaded target domain: ${clean}`));
        sessionStorage.removeItem('citeaura_pending_domain');
        localStorage.removeItem('citeaura_pending_domain');
      }
      if (pendingAudit && Array.isArray(pendingAudit.checks)) {
        const preflightBox = document.getElementById('ob-preflight');
        if (preflightBox) {
          preflightBox.style.display = 'flex';
          preflightBox.innerHTML = `<strong style="font-size:var(--fs-2);">${t('onboard.audit_findings_title', {}, 'Your public audit findings')}</strong>${pendingAudit.checks.slice(0, 6).map((check) => `<div style="display:flex;justify-content:space-between;gap:var(--sp-3);font-size:var(--fs-2);"><span>${escapeHtml(check.name || 'Site check')}</span><span class="${check.ok ? 'pill-good' : 'pill-bad'}">${check.ok ? 'OK' : escapeHtml(check.message || 'Needs review')}</span></div>`).join('')}`;
        }
      }
    } catch (e) {
      console.warn('Could not auto-fill domain:', e);
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const url = document.getElementById('ob-url').value.trim();
      const name = document.getElementById('ob-name').value.trim();
      const selectedMode = document.querySelector('input[name="ob-mode"]:checked')?.value || 'audit';
      const no_sample = selectedMode !== 'baseline';
      const submitBtn = document.getElementById('ob-submit');
      const preflightBox = document.getElementById('ob-preflight');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.checking_site', {}, 'Checking site...')}`;

      try {
        analytics.track(no_sample ? 'audit_only_selected' : 'full_baseline_selected', { source: 'onboarding' });
        const preflight = await projects.preflight({ url });
        const site = preflight?.site || {};
        if (preflightBox) {
          const checks = site.checks || [];
          preflightBox.style.display = 'flex';
          preflightBox.innerHTML = checks.map((check) => (
            `<div style="display:flex;justify-content:space-between;gap:var(--sp-3);font-size:var(--fs-2);">
              <span>${escapeHtml(check.name || 'Site check')}</span>
              <span class="${check.ok ? 'pill-good' : 'pill-bad'}">${check.ok ? 'OK' : escapeHtml(check.message || 'Failed')}</span>
            </div>`
          )).join('');
        }
        if (site.ready === false) {
          const failed = (site.checks || []).find((check) => !check.ok);
          throw { error: 'site_not_ready', detail: failed?.action || failed?.message || 'Site is not reachable yet' };
        }
        if (!no_sample && preflight && preflight.can_sample === false) {
          throw {
            error: 'sampling_not_configured',
            detail: 'No model access is configured yet. Select Audit only to get the diagnostic now, or connect a BYOK key in Model Keys (BYOK) and retry the baseline.',
          };
        }

        submitBtn.innerHTML = `<span class="spin"></span> ${t('common.initializing', {}, 'Initializing pipeline...')}`;
        const auditId = sessionStorage.getItem('citeaura_pending_audit_id') || undefined;
        const res = await projects.create({ url, name: name || undefined, no_sample, skip_llm: false, audit_id: auditId });
        toast.success(
          no_sample
            ? t('onboard.created_audit_only', {}, 'Brand pipeline started. Site audit will run without AI sampling.')
            : t('onboard.created_success', {}, 'Brand pipeline started! Crawling and analyzing...'),
        );
        await ctx.reloadProjects();
        if (res && res.project_id) {
          ctx.setActiveProject(res.project_id);
        }
        sessionStorage.removeItem('citeaura_pending_audit_id');
        sessionStorage.removeItem('citeaura_pending_audit');
        ctx.navigate('#/overview');
        if (res?.project_id && res?.job_id && typeof ctx.openTelemetry === 'function') {
          ctx.openTelemetry(res.job_id, res.action || (no_sample ? 'bootstrap' : 'autopilot'), {
            projectId: res.project_id,
            onComplete: async () => {
              await ctx.reloadProjects();
              await ctx.reloadCurrentView();
            },
          });
        }
      } catch (err) {
        if (err.error === 'sampling_not_configured') {
          toast.info(err.detail);
          submitBtn.disabled = false;
          submitBtn.innerHTML = `<span>${t('onboard.start_measurement', {}, 'Initialize Brand Pipeline')}</span>`;
          return;
        }
        toast.error(tError(err));
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('onboard.start_measurement', {}, 'Initialize Brand Pipeline')}</span>`;
      }
    });
  },
};
