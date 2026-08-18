/**
 * Brand onboarding
 */

import { projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

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

            <div class="card" style="background:var(--deep);padding:var(--sp-4);border-radius:var(--r-md);gap:var(--sp-2);">
              <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;user-select:none;">
                <input type="checkbox" id="ob-nosample" style="margin-top:2px;">
                <div style="font-size:var(--fs-2);">
                  <strong style="color:var(--ink);">${t('onboard.skip_sample_title', {}, 'Skip initial AI sampling')}</strong>
                  <div style="color:var(--muted);margin-top:2px;">
                    ${t('onboard.skip_sample_desc', {}, 'Run crawl, facts, and tickets only. Paid plans can sample the first matrix from the CiteAura platform pool without adding every API key.')}
                  </div>
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
    } catch (e) {
      console.warn('Could not auto-fill domain:', e);
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const url = document.getElementById('ob-url').value.trim();
      const name = document.getElementById('ob-name').value.trim();
      const no_sample = document.getElementById('ob-nosample').checked;
      const submitBtn = document.getElementById('ob-submit');
      const preflightBox = document.getElementById('ob-preflight');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.checking_site', {}, 'Checking site...')}`;

      try {
        const preflight = await projects.preflight({ url });
        const site = preflight?.site || {};
        if (preflightBox) {
          const checks = site.checks || [];
          preflightBox.style.display = 'flex';
          preflightBox.innerHTML = checks.map((check) => (
            `<div style="display:flex;justify-content:space-between;gap:var(--sp-3);font-size:var(--fs-2);">
              <span>${check.name}</span>
              <span class="${check.ok ? 'pill-good' : 'pill-bad'}">${check.ok ? 'OK' : (check.message || 'Failed')}</span>
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
            detail: 'Configure an API key or skip initial sampling to create an audit-only project.',
          };
        }

        submitBtn.innerHTML = `<span class="spin"></span> ${t('common.initializing', {}, 'Initializing pipeline...')}`;
        const res = await projects.create({ url, name: name || undefined, no_sample, skip_llm: false });
        toast.success(
          no_sample
            ? t('onboard.created_audit_only', {}, 'Brand pipeline started. Site audit will run without AI sampling.')
            : t('onboard.created_success', {}, 'Brand pipeline started! Crawling and analyzing...'),
        );
        await ctx.reloadProjects();
        if (res && res.project_id) {
          ctx.setActiveProject(res.project_id);
        }
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
          toast.error(err.detail);
          ctx.navigate('#/engine-settings');
          return;
        }
        toast.error(t(err.error, {}, err.detail || 'Failed to initialize brand'));
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('onboard.start_measurement', {}, 'Initialize Brand Pipeline')}</span>`;
      }
    });
  },
};
