/**
 *  (Delivery Branding & White-Label)
 */

import { branding } from '../api.js';
import { t, tError } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';
import { confirmModal } from '../components/modal.js';

export default {
  render: async (ctx) => {
    let brandConfig = { available: false, can_edit: false };
    let loadError = null;
    try {
      brandConfig = await branding.get();
    } catch (err) {
      loadError = err;
    }
    const canEdit = Boolean(brandConfig.can_edit);
    const available = Boolean(brandConfig.available);
    const accessNote = loadError
      ? tError(loadError, 'branding.load_failed')
      : !available
        ? t('branding.plan_required', { plan: brandConfig.plan || '—' }, `White-label delivery branding requires the Agency plan. Current plan: ${brandConfig.plan || '—'}.`)
        : !canEdit
          ? t('branding.owner_required', {}, 'Only the workspace owner can edit delivery branding.')
          : '';

    if (loadError) {
      return `
        <div class="app-view-container">
          <div class="view-header">
            <div class="view-title-group">
              <h1 class="view-title">${t('branding.title', {}, 'White-Label & Delivery Branding')}</h1>
              <p class="view-desc">${t('branding.desc', {}, 'Customize the header logo, agency name, and confidentiality notices exported in client delivery packs.')}</p>
            </div>
          </div>
          <div class="empty" role="alert">
            <strong>${t('branding.load_failed_title', {}, 'Branding settings unavailable')}</strong>
            <p>${escapeHtml(accessNote)}</p>
            <button type="button" id="btn-reload-branding" class="btn btn-secondary btn-sm">${t('common.retry', {}, 'Retry')}</button>
          </div>
        </div>
      `;
    }

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
            ${canEdit ? `<button type="button" id="btn-reset-branding" class="btn btn-secondary btn-sm">${t('branding.reset_btn', {}, 'Reset Branding')}</button>` : ''}
            <button type="button" id="btn-save-branding" class="btn btn-primary btn-sm" ${canEdit ? '' : 'disabled'}>
              <span>${t('common.save_changes', {}, 'Save Branding')}</span>
            </button>
          </div>
        </div>

        ${accessNote ? `<div class="read-only-note" role="status">${escapeHtml(accessNote)}</div>` : ''}

        <div class="card" style="max-width:680px;gap:var(--sp-4);">
          <div class="field">
            <label for="brand-company-name">${t('branding.agency_name_label', {}, 'Agency / Consultant Organization Name')}</label>
            <input type="text" id="brand-company-name" class="input" value="${escapeHtml(brandConfig.company_name || '')}" placeholder="Apex Growth Digital" ${canEdit ? '' : 'disabled'}>
          </div>

          <div class="field">
            <label for="brand-logo-file">${t('branding.logo_url_label', {}, 'Custom Logo (PNG, JPEG, or WebP)')}</label>
            <div class="branding-logo-row">
              <span class="branding-logo-preview" id="brand-logo-preview-wrap" ${brandConfig.logo_data_url ? '' : 'hidden'}>
                <img id="brand-logo-preview" src="${escapeHtml(brandConfig.logo_data_url || '')}" alt="${escapeHtml(t('branding.logo_preview_alt', {}, 'Configured delivery logo'))}">
              </span>
              <label class="btn btn-secondary btn-sm branding-file-button">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span>${t('common.choose_file', {}, 'Choose File')}</span>
                <input type="file" id="brand-logo-file" accept="image/png,image/jpeg,image/webp" ${canEdit ? '' : 'disabled'}>
              </label>
              <span id="brand-logo-filename" class="branding-logo-filename">${brandConfig.logo_data_url ? t('branding.logo_configured', {}, 'Logo configured (Click to replace)') : t('common.no_file_chosen', {}, 'No file chosen')}</span>
            </div>
            <div class="field-hint">${t('branding.logo_hint', {}, 'PNG, JPEG, or WebP. Maximum 512 KB.')}</div>
          </div>

          <div class="field">
            <label for="brand-accent-color">${t('branding.accent_color_label', {}, 'Accent Color')}</label>
            <input type="color" id="brand-accent-color" class="input branding-color-input" value="${escapeHtml(brandConfig.accent_color || '#1F4E79')}" ${canEdit ? '' : 'disabled'}>
          </div>

          <div class="field">
            <label for="brand-footer-text">${t('branding.footer_label', {}, 'Report Footer & Copyright Notice')}</label>
            <input type="text" id="brand-footer-text" class="input" value="${escapeHtml(brandConfig.footer_text || '')}" placeholder="Prepared exclusively for client. Confidential." ${canEdit ? '' : 'disabled'}>
          </div>

          <div class="branding-toggle">
            <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;">
              <input type="checkbox" id="brand-enabled" ${brandConfig.enabled ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>
              <div style="font-size:var(--fs-2);">
                <strong style="color:var(--ink);">${t('branding.hide_badge_title', {}, 'Enable custom branding in client delivery packs')}</strong>
                <div style="color:var(--muted);margin-top:2px;">
                  ${t('branding.hide_badge_desc', {}, 'Requires an Agency plan and adds your header and footer to generated delivery documents.')}
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.getElementById('btn-reload-branding')?.addEventListener('click', () => ctx.reloadCurrentView());

    const logoInput = document.getElementById('brand-logo-file');
    const logoFilename = document.getElementById('brand-logo-filename');
    const logoPreview = document.getElementById('brand-logo-preview');
    const logoPreviewWrap = document.getElementById('brand-logo-preview-wrap');
    const initialLogo = logoPreview?.getAttribute('src') || '';
    if (logoInput && logoFilename) {
      logoInput.addEventListener('change', async () => {
        const file = logoInput.files?.[0];
        if (!file) {
          logoFilename.textContent = initialLogo
            ? t('branding.logo_configured', {}, 'Logo configured (Click to replace)')
            : t('common.no_file_chosen', {}, 'No file chosen');
          if (logoPreview && initialLogo) logoPreview.src = initialLogo;
          if (logoPreviewWrap) logoPreviewWrap.hidden = !initialLogo;
          return;
        }
        try {
          const dataUrl = await readLogo(file);
          logoFilename.textContent = file.name;
          if (logoPreview) logoPreview.src = dataUrl;
          if (logoPreviewWrap) logoPreviewWrap.hidden = false;
        } catch (err) {
          logoInput.value = '';
          toast.error(err.message || tError(err));
        }
      });
    }

    document.getElementById('btn-save-branding')?.addEventListener('click', async () => {
      const saveBtn = document.getElementById('btn-save-branding');
      const company_name = document.getElementById('brand-company-name')?.value.trim();
      const file = document.getElementById('brand-logo-file')?.files?.[0];
      const footer_text = document.getElementById('brand-footer-text')?.value.trim();
      const accent_color = document.getElementById('brand-accent-color')?.value;
      const enabled = document.getElementById('brand-enabled')?.checked;

      saveBtn.disabled = true;
      saveBtn.innerHTML = `<span class="spin"></span> ${t('common.saving', {}, 'Saving...')}`;
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
        await ctx.reloadCurrentView();
      } catch (err) {
        toast.error(tError(err));
        saveBtn.disabled = false;
        saveBtn.innerHTML = `<span>${t('common.save_changes', {}, 'Save Branding')}</span>`;
      }
    });

    document.getElementById('btn-reset-branding')?.addEventListener('click', async () => {
      const confirmed = await confirmModal(
        t('branding.reset_confirm', {}, 'Remove the saved logo, accent color, company name, and footer? This cannot be undone.'),
        { title: t('branding.reset_btn', {}, 'Reset Branding'), confirmText: t('branding.reset_btn', {}, 'Reset Branding'), isDanger: true },
      );
      if (!confirmed) return;
      try {
        await branding.delete();
        toast.success(t('branding.reset_success', {}, 'Delivery branding reset'));
        await ctx.reloadCurrentView();
      } catch (err) {
        toast.error(tError(err));
      }
    });
  },
};

function readLogo(file) {
  if (file.size > 512 * 1024) {
    return Promise.reject(new Error(t('branding.logo_too_large', {}, 'Logo must not exceed 512 KB.')));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result || '')));
    reader.addEventListener('error', () => reject(new Error(t('branding.logo_read_failed', {}, 'Failed to read the logo file.'))));
    reader.readAsDataURL(file);
  });
}
