/**
 *  (Delivery Branding & White-Label)
 */

import { branding } from '../api.js';
import { t, tError } from '../i18n.js';
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
            <button type="button" id="btn-save-branding" class="btn btn-primary btn-sm" ${brandConfig.can_edit ? '' : 'disabled'}>
              <span>${t('common.save_changes', {}, 'Save Branding')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="max-width:680px;gap:var(--sp-4);">
          <div class="field" style="margin:0;">
            <label for="brand-company-name">${t('branding.agency_name_label', {}, 'Agency / Consultant Organization Name')}</label>
            <input type="text" id="brand-company-name" class="input" value="${brandConfig.company_name || ''}" placeholder="Apex Growth Digital" ${brandConfig.can_edit ? '' : 'disabled'}>
          </div>

          <div class="field" style="margin:0;">
            <label for="brand-logo-file">${t('branding.logo_url_label', {}, 'Custom Logo (PNG, JPEG, or WebP)')}</label>
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              <label class="btn btn-secondary btn-sm" style="cursor:pointer;margin:0;display:inline-flex;align-items:center;gap:var(--sp-2);">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span>${t('common.choose_file', {}, 'Choose File')}</span>
                <input type="file" id="brand-logo-file" accept="image/png,image/jpeg,image/webp" style="display:none;" ${brandConfig.can_edit ? '' : 'disabled'}>
              </label>
              <span id="brand-logo-filename" style="color:var(--muted);font-size:var(--fs-1);">${brandConfig.logo_data_url ? t('branding.logo_configured', {}, 'Logo configured (Click to replace)') : t('common.no_file_chosen', {}, 'No file chosen')}</span>
            </div>
          </div>

          <div class="field" style="margin:0;">
            <label for="brand-accent-color">${t('branding.accent_color_label', {}, 'Accent Color')}</label>
            <input type="color" id="brand-accent-color" class="input" value="${brandConfig.accent_color || '#1F4E79'}" ${brandConfig.can_edit ? '' : 'disabled'}>
          </div>

          <div class="field" style="margin:0;">
            <label for="brand-footer-text">${t('branding.footer_label', {}, 'Report Footer & Copyright Notice')}</label>
            <input type="text" id="brand-footer-text" class="input" value="${brandConfig.footer_text || ''}" placeholder="Prepared exclusively for client. Confidential." ${brandConfig.can_edit ? '' : 'disabled'}>
          </div>

          <div style="background:var(--page);padding:var(--sp-4);border:1px solid var(--line);border-radius:var(--r-md);">
            <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;">
              <input type="checkbox" id="brand-enabled" ${brandConfig.enabled ? 'checked' : ''} style="margin-top:2px;" ${brandConfig.can_edit ? '' : 'disabled'}>
              <div style="font-size:var(--fs-2);">
                <strong style="color:var(--ink);">${t('branding.hide_badge_title', {}, 'Enable custom branding in client delivery packs')}</strong>
                <div style="color:var(--muted);margin-top:2px;">
                  ${t('branding.hide_badge_desc', {}, 'Requires an Agency or Enterprise plan and adds your header and footer to generated delivery documents.')}
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const logoInput = document.getElementById('brand-logo-file');
    const logoFilename = document.getElementById('brand-logo-filename');
    if (logoInput && logoFilename) {
      logoInput.addEventListener('change', () => {
        const file = logoInput.files?.[0];
        logoFilename.textContent = file ? file.name : t('common.no_file_chosen', {}, 'No file chosen');
      });
    }

    document.getElementById('btn-save-branding')?.addEventListener('click', async () => {
      const company_name = document.getElementById('brand-company-name')?.value.trim();
      const file = document.getElementById('brand-logo-file')?.files?.[0];
      const footer_text = document.getElementById('brand-footer-text')?.value.trim();
      const accent_color = document.getElementById('brand-accent-color')?.value;
      const enabled = document.getElementById('brand-enabled')?.checked;

      try {
        const logo_data_url = file ? await readLogo(file) : undefined;
        const current = await branding.get();
        await branding.save({
          enabled,
          company_name,
          logo_data_url: logo_data_url === undefined ? current.logo_data_url || '' : logo_data_url,
          accent_color,
          footer_text,
        });
        toast.success(t('branding.saved_success', {}, 'Delivery branding updated successfully'));
      } catch (err) {
        toast.error(tError(err));
      }
    });
  },
};

function readLogo(file) {
  if (file.size > 512 * 1024) {
    return Promise.reject(new Error('Logo must not exceed 512 KB'));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result || '')));
    reader.addEventListener('error', () => reject(new Error('Failed to read logo file')));
    reader.readAsDataURL(file);
  });
}
