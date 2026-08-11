/**
 *  (Integrations)
 */

import { integrations } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';

export default {
  render: async (ctx) => {
    let intList = [];
    try {
      intList = await integrations.list().catch(() => []);
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('integrations.title', {}, 'External SEO & Data Integrations')}</h1>
            <p class="view-desc">
              ${t('integrations.desc', {}, 'Connect Google Search Console and Semrush to cross-reference organic search queries against generative AI recommendations.')}
            </p>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:var(--sp-6);">
          <!-- Google Search Console -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-4);">Google Search Console</strong>
              <span class="tag tag-dim">OAuth 2.0</span>
            </div>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Import search impressions, clicks, and ranking queries to discover high-value prompt topics.
            </p>
            <button type="button" class="btn btn-secondary btn-sm btn-connect-gsc" style="align-self:flex-start;">
              ${t('integrations.connect_gsc', {}, 'Authorize Search Console')}
            </button>
          </div>

          <!-- Semrush -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <strong style="font-size:var(--fs-4);">Semrush API</strong>
              <span class="tag tag-dim">API Key</span>
            </div>
            <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">
              Sync competitor organic keyword overlap and domain authority metrics.
            </p>
            <button type="button" class="btn btn-secondary btn-sm btn-connect-semrush" style="align-self:flex-start;">
              ${t('integrations.connect_semrush', {}, 'Configure Semrush Key')}
            </button>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.querySelector('.btn-connect-semrush')?.addEventListener('click', () => {
      openModal({
        title: 'Configure Semrush API',
        content: `
          <div class="field" style="margin:0;">
            <label>Semrush API Key *</label>
            <input type="password" id="semrush-key-input" class="input" placeholder="••••••••••••••••">
          </div>
        `,
        confirmText: 'Save Key',
        onConfirm: async () => {
          const api_key = document.getElementById('semrush-key-input')?.value.trim();
          if (!api_key) return false;

          try {
            await integrations.saveSemrush({ api_key });
            toast.success('Semrush API key saved');
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to save Semrush key'));
            return false;
          }
        },
      });
    });
  },
};
