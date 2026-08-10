/**
 * 模型与测量设置视图 (Engine Keys & BYOK)
 */

import { settings } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';

const AVAILABLE_ENGINES = [
  { code: 'deepseek', name: 'DeepSeek (V3 / R1)', provider: 'DeepSeek Official API' },
  { code: 'openai', name: 'OpenAI (GPT-4o / Search)', provider: 'OpenAI Platform' },
  { code: 'claude', name: 'Anthropic (Claude)', provider: 'Anthropic Console' },
  { code: 'gemini', name: 'Google (Gemini)', provider: 'Google AI Studio' },
  { code: 'glm', name: 'Zhipu AI (GLM)', provider: 'Zhipu BigModel' },
  { code: 'doubao', name: 'Doubao', provider: 'Volcengine Ark' },
  { code: 'kimi', name: 'Kimi', provider: 'Moonshot AI' },
  { code: 'minimax', name: 'MiniMax', provider: 'MiniMax Platform' },
  { code: 'grok', name: 'Grok', provider: 'xAI Console' },
  { code: 'perplexity', name: 'Perplexity', provider: 'Perplexity API' },
];

export default {
  render: async (ctx) => {
    let configuredKeys = [];
    try {
      configuredKeys = await settings.getKeys().catch(() => []);
    } catch (e) {}

    const keyMap = {};
    configuredKeys.forEach((k) => {
      keyMap[k.engine_code] = k;
    });

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('engine_settings.title', {}, 'BYOK Model API Keys & Measurement Settings')}</h1>
            <p class="view-desc">
              ${t('engine_settings.desc', {}, 'Bring Your Own Key (BYOK) for direct provider billing with zero middleman markup. Keys are stored via hardware-grade AES-256-GCM encryption and injected only during runtime.')}
            </p>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('engine_settings.matrix_title', {}, 'Supported Model Matrix Endpoints')}</h3>
          </div>

          <div class="tbl" style="overflow-x:auto;">
            <table class="table">
              <thead>
                <tr>
                  <th>${t('engine_settings.col_model', {}, 'Model Provider')}</th>
                  <th>${t('engine_settings.col_env', {}, 'Engine Code')}</th>
                  <th>${t('common.status', {}, 'Status')}</th>
                  <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                </tr>
              </thead>
              <tbody>
                ${AVAILABLE_ENGINES.map((eng) => {
                  const conf = keyMap[eng.code];
                  const isSet = !!conf;
                  return `
                    <tr>
                      <td>
                        <strong>${eng.name}</strong>
                        <div style="font-size:11px;color:var(--muted);">${eng.provider}</div>
                      </td>
                      <td><span class="num">${eng.code}</span></td>
                      <td>
                        <span class="tag ${isSet ? 'pill-good' : 'tag-dim'}">
                          ${isSet ? 'Encrypted & Active' : 'Unconfigured'}
                        </span>
                      </td>
                      <td style="text-align:right;">
                        <div style="display:inline-flex;gap:var(--sp-2);">
                          ${
                            isSet
                              ? `<button type="button" class="btn btn-secondary btn-sm btn-test-key" data-code="${eng.code}">${t('engine_settings.test_key', {}, 'Test')}</button>
                                 <button type="button" class="btn btn-ghost btn-sm btn-del-key" data-code="${eng.code}" style="color:var(--bad);">✕</button>`
                              : `<button type="button" class="btn btn-primary btn-sm btn-set-key" data-code="${eng.code}" data-name="${eng.name}">
                                 ${t('engine_settings.configure_key', {}, 'Configure Key')}
                               </button>`
                          }
                        </div>
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.querySelectorAll('.btn-set-key').forEach((btn) => {
      btn.addEventListener('click', () => {
        const code = btn.getAttribute('data-code');
        const name = btn.getAttribute('data-name');

        openModal({
          title: `Configure ${name}`,
          content: `
            <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
              <div class="field" style="margin:0;">
                <label>API Key *</label>
                <input type="password" id="input-api-key" class="input" placeholder="sk-••••••••••••••••" required>
                <div class="field-hint">Encrypted with AES-256-GCM. Plaintext is never returned in API responses.</div>
              </div>
            </div>
          `,
          confirmText: 'Save Key',
          onConfirm: async () => {
            const keyValue = document.getElementById('input-api-key')?.value.trim();
            if (!keyValue) return false;

            try {
              await settings.saveKey(code, keyValue);
              toast.success(`${name} API key encrypted and saved`);
              ctx.navigate('#/engine-settings');
              return true;
            } catch (err) {
              toast.error(t(err.error, {}, err.detail || 'Failed to save key'));
              return false;
            }
          },
        });
      });
    });

    document.querySelectorAll('.btn-test-key').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const code = btn.getAttribute('data-code');
        btn.disabled = true;
        btn.innerHTML = `<span class="spin"></span>`;
        try {
          await settings.testKey(code);
          toast.success('Key connection test passed!');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Key test failed'));
        } finally {
          btn.disabled = false;
          btn.innerHTML = t('engine_settings.test_key', {}, 'Test');
        }
      });
    });

    document.querySelectorAll('.btn-del-key').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const code = btn.getAttribute('data-code');
        try {
          await settings.deleteKey(code);
          toast.success('Key removed');
          ctx.navigate('#/engine-settings');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to remove key'));
        }
      });
    });
  },
};
