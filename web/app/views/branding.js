/**
 * 白标品牌与报告定制视图 (Delivery Branding & White-Label)
 */

import { branding } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

export default {
  render: async (ctx) => {
    let brandConfig = {};
    try {
      brandConfig = await branding.get().catch(() => ({}));
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('branding.title', {}, 'White-Label & Delivery Branding')}</h1>
            <p class="view-desc">
              ${t('branding.desc', {}, 'Customize the header logo, agency name, and confidentiality notices exported in client delivery packs.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-branding" class="btn btn-primary btn-sm">
              <span>${t('common.save_changes', {}, 'Save Branding')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="max-width:680px;gap:var(--sp-4);">
          <div class="field" style="margin:0;">
            <label for="brand-agency-name">${t('branding.agency_name_label', {}, 'Agency / Consultant Organization Name')}</label>
            <input type="text" id="brand-agency-name" class="input" value="${brandConfig.agency_name || ''}" placeholder="Apex Growth Digital">
          </div>

          <div class="field" style="margin:0;">
            <label for="brand-logo-url">${t('branding.logo_url_label', {}, 'Custom Logo URL (PNG/SVG)')}</label>
            <input type="url" id="brand-logo-url" class="input" value="${brandConfig.logo_url || ''}" placeholder="https://youragency.com/assets/logo.png">
          </div>

          <div class="field" style="margin:0;">
            <label for="brand-footer-text">${t('branding.footer_label', {}, 'Report Footer & Copyright Notice')}</label>
            <input type="text" id="brand-footer-text" class="input" value="${brandConfig.footer_text || ''}" placeholder="Prepared exclusively for client. Confidential.">
          </div>

          <div class="card" style="background:var(--page);padding:var(--sp-4);border-radius:var(--r-md);">
            <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;">
              <input type="checkbox" id="brand-hide-citeaura" ${brandConfig.hide_badge ? 'checked' : ''} style="margin-top:2px;">
              <div style="font-size:var(--fs-2);">
                <strong style="color:var(--ink);">${t('branding.hide_badge_title', {}, 'Hide CiteAura branding in client delivery packs')}</strong>
                <div style="color:var(--muted);margin-top:2px;">
                  ${t('branding.hide_badge_desc', {}, 'Requires Agency or Enterprise plan. Delivery ZIP will contain zero references to CiteAura.')}
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.getElementById('btn-save-branding')?.addEventListener('click', async () => {
      const agency_name = document.getElementById('brand-agency-name')?.value.trim();
      const logo_url = document.getElementById('brand-logo-url')?.value.trim();
      const footer_text = document.getElementById('brand-footer-text')?.value.trim();
      const hide_badge = document.getElementById('brand-hide-citeaura')?.checked;

      try {
        await branding.save({ agency_name, logo_url, footer_text, hide_badge });
        toast.success(t('branding.saved_success', {}, 'Delivery branding updated successfully'));
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to update branding'));
      }
    });
  },
};
