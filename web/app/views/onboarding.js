/**
 *  (Onboarding)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: (ctx) => {
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

            <div class="card" style="background:var(--deep);padding:var(--sp-4);border-radius:var(--r-md);gap:var(--sp-2);">
              <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;user-select:none;">
                <input type="checkbox" id="ob-nosample" style="margin-top:2px;">
                <div style="font-size:var(--fs-2);">
                  <strong style="color:var(--ink);">${t('onboard.skip_llm_title', {}, 'Skip initial LLM sampling')}</strong>
                  <div style="color:var(--muted);margin-top:2px;">
                    ${t('onboard.skip_llm_desc', {}, 'Only run fact crawling and question generation; run model sampling later after configuring API Keys in Settings.')}
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

    // Auto-detect pending domain from scanner parameter
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
      const skip_llm = document.getElementById('ob-nosample').checked;
      const submitBtn = document.getElementById('ob-submit');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="spin"></span> ${t('common.initializing', {}, 'Initializing pipeline...')}`;

      try {
        const res = await projects.create({ url, name: name || undefined, skip_llm });
        toast.success(t('onboard.created_success', {}, 'Brand pipeline started! Crawling and analyzing...'));
        await ctx.reloadProjects();
        if (res && res.project_id) {
          ctx.setActiveProject(res.project_id);
        }
        ctx.navigate('#/overview');
        if (res?.project_id && res?.job_id && typeof ctx.openTelemetry === 'function') {
          ctx.openTelemetry(res.job_id, res.action || (skip_llm ? 'bootstrap' : 'autopilot'), {
            projectId: res.project_id,
            onComplete: async () => {
              await ctx.reloadProjects();
              await ctx.reloadCurrentView();
            },
          });
        }
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to initialize brand'));
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>${t('onboard.start_measurement', {}, 'Initialize Brand Pipeline')}</span>`;
      }
    });
  },
};
