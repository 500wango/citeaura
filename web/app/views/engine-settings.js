/**
 *  (Engine Keys & BYOK)
 */

import { settings } from '../api.js?v=3.8';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';

const AVAILABLE_ENGINES = [
  { code: 'openai', name: 'OpenAI', provider: 'OpenAI Platform' },
  { code: 'claude', name: 'Anthropic', provider: 'Anthropic Console' },
  { code: 'gemini', name: 'Google', provider: 'Google AI Studio' },
  { code: 'grok', name: 'xAI', provider: 'xAI Console' },
  { code: 'perplexity', name: 'Perplexity', provider: 'Perplexity API' },
  { code: 'deepseek', name: 'DeepSeek', provider: 'DeepSeek Platform' },
];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function customProviderForm(provider = null) {
  const editing = Boolean(provider);
  const name = escapeHtml(provider?.name || '');
  const baseUrl = escapeHtml(provider?.base_url || '');
  const modelId = escapeHtml(provider?.model_id || '');
  return `
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <div class="field" style="margin:0;">
        <label for="custom-provider-name">Provider Name *</label>
        <input type="text" id="custom-provider-name" class="input" placeholder="My model gateway" maxlength="128" value="${name}" ${editing ? 'readonly' : ''} required>
      </div>
      <div class="field" style="margin:0;">
        <label for="custom-provider-url">Base URL *</label>
        <input type="url" id="custom-provider-url" class="input" placeholder="https://gateway.example.com/v1" value="${baseUrl}" required>
        <div class="field-hint">OpenAI-compatible HTTPS endpoint. Do not include /chat/completions.</div>
      </div>
      <div class="field" style="margin:0;">
        <label for="custom-provider-model">Model ID *</label>
        <input type="text" id="custom-provider-model" class="input" placeholder="provider/model-name" maxlength="255" value="${modelId}" required>
      </div>
      <div class="field" style="margin:0;">
        <label for="custom-provider-key">API Key *</label>
        <input type="password" id="custom-provider-key" class="input" placeholder="sk-••••••••••••••••" required>
        <div class="field-hint">The connection is tested before the encrypted configuration is saved.</div>
      </div>
      <div id="custom-provider-status" role="status" aria-live="polite" style="min-height:20px;font-size:var(--fs-2);color:var(--muted);"></div>
    </div>
  `;
}

function customProviderPayload() {
  return {
    name: document.getElementById('custom-provider-name')?.value.trim() || '',
    base_url: document.getElementById('custom-provider-url')?.value.trim() || '',
    model_id: document.getElementById('custom-provider-model')?.value.trim() || '',
    market: 'global',
    api_key: document.getElementById('custom-provider-key')?.value.trim() || '',
  };
}

function customProviderErrorMessage(err) {
  const diagnostic = err?.detail || err?.data?.detail || err?.error;
  const messages = {
    provider_http_400: 'The provider rejected the request. Verify the Base URL and exact Model ID.',
    provider_http_401: 'Authentication failed. Verify the API Key.',
    provider_http_403: 'The API Key cannot access this model.',
    provider_http_404: 'The endpoint or Model ID was not found.',
    provider_http_429: 'The provider rate limit or account quota was reached.',
    provider_timeout: 'The provider did not respond before the connection test timed out.',
    provider_request_failed: 'The provider returned an invalid response or could not be reached.',
    network_error: 'CiteAura could not reach the server. Check the network and try again.',
  };
  if (messages[diagnostic]) return messages[diagnostic];
  if (typeof diagnostic === 'string' && diagnostic.startsWith('provider_http_')) {
    return `The provider returned HTTP ${diagnostic.slice('provider_http_'.length)}.`;
  }
  return 'Failed to connect custom provider.';
}

async function saveCustomProvider(ctx, successMessage) {
  const inputs = [
    document.getElementById('custom-provider-name'),
    document.getElementById('custom-provider-url'),
    document.getElementById('custom-provider-model'),
    document.getElementById('custom-provider-key'),
  ];
  const invalid = inputs.find((input) => input && !input.checkValidity());
  if (invalid) {
    invalid.reportValidity();
    return false;
  }

  const payload = customProviderPayload();
  const modal = document.getElementById('modal-root');
  const confirmButton = modal?.querySelector('.btn-confirm');
  const status = document.getElementById('custom-provider-status');
  const originalButton = confirmButton?.innerHTML || 'Test & Save';
  inputs.forEach((input) => { if (input) input.disabled = true; });
  if (confirmButton) {
    confirmButton.disabled = true;
    confirmButton.setAttribute('aria-busy', 'true');
    confirmButton.innerHTML = '<span class="spin"></span><span>Testing...</span>';
  }
  if (status) {
    status.style.color = 'var(--muted)';
    status.textContent = 'Testing endpoint, API Key, and Model ID...';
  }

  let saved = false;
  try {
    await settings.saveCustomProvider(payload);
    saved = true;
    await ctx.reloadCurrentView();
    toast.success(successMessage);
    return true;
  } catch (err) {
    const message = customProviderErrorMessage(err);
    if (status) {
      status.style.color = 'var(--bad)';
      status.textContent = message;
    }
    toast.error(message, 6000);
    return false;
  } finally {
    if (!saved) {
      inputs.forEach((input) => { if (input) input.disabled = false; });
      if (confirmButton) {
        confirmButton.disabled = false;
        confirmButton.removeAttribute('aria-busy');
        confirmButton.innerHTML = originalButton;
      }
    }
  }
}

export default {
  render: async (ctx) => {
    let configuredKeys = [];
    let customProviders = [];
    let apiTokens = [];
    try {
      [configuredKeys, customProviders, apiTokens] = await Promise.all([
        settings.getKeys().catch(() => []),
        settings.getCustomProviders().catch(() => []),
        settings.getApiTokens().catch(() => []),
      ]);
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
              ${t('engine_settings.desc', {}, 'Each configured endpoint is a sampling engine: built-in providers and custom OpenAI-compatible models share the same measurement matrix. Perplexity is web-grounded; others use model knowledge.')}
            </p>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('engine_settings.matrix_title', {}, 'Supported Model Matrix Endpoints')}</h3>
            <button type="button" id="btn-add-custom-provider" class="btn btn-primary btn-sm">
              <img src="/site-assets/icons/plus.svg" width="14" height="14" alt="">
              <span>Add Provider</span>
            </button>
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
              <tbody id="supported-model-endpoints">
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
                ${customProviders.map((provider) => `
                  <tr data-provider-kind="custom">
                    <td>
                      <strong>${escapeHtml(provider.name)}</strong>
                      <div style="font-size:11px;color:var(--muted);">Third-party / OpenAI-compatible</div>
                    </td>
                    <td>
                      <span class="num">${escapeHtml(provider.code)}</span>
                      <div class="num" style="font-size:11px;color:var(--muted);margin-top:var(--sp-1);word-break:break-all;">Base URL: ${escapeHtml(provider.base_url)}</div>
                      <div class="num" style="font-size:11px;color:var(--muted);word-break:break-all;">Model ID: ${escapeHtml(provider.model_id)}</div>
                    </td>
                    <td><span class="tag pill-good">Encrypted & Active</span></td>
                    <td style="text-align:right;">
                      <div style="display:inline-flex;gap:var(--sp-2);">
                        <button type="button" class="btn btn-secondary btn-sm btn-edit-custom"
                          data-name="${escapeHtml(provider.name)}"
                          data-base-url="${escapeHtml(provider.base_url)}"
                          data-model-id="${escapeHtml(provider.model_id)}">Edit</button>
                        <button type="button" class="btn btn-ghost btn-sm btn-del-custom" data-code="${escapeHtml(provider.code)}" style="color:var(--bad);">✕</button>
                      </div>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>

        <section class="card" style="gap:var(--sp-3);margin-top:var(--sp-4);">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div>
              <h2 style="font-size:var(--fs-4);font-weight:600;margin:0;">Public API & MCP access</h2>
              <p style="font-size:var(--fs-2);color:var(--muted);margin:4px 0 0;max-width:70ch;">Create a read-only token for reporting tools or an MCP client. Tokens are shown once, stored as hashes, and can be revoked by an owner.</p>
            </div>
            <button type="button" id="btn-create-api-token" class="btn btn-secondary btn-sm">Create read-only token</button>
          </div>
          ${apiTokens.length ? `<div class="tbl" style="overflow-x:auto;"><table class="table"><thead><tr><th>Name</th><th>Prefix</th><th>Status</th><th>Last used</th><th style="text-align:right;">Action</th></tr></thead><tbody>${apiTokens.map((token) => `<tr><td>${escapeHtml(token.name)}</td><td class="num">${escapeHtml(token.prefix)}…</td><td><span class="tag ${token.revoked_at ? 'tag-dim' : 'pill-good'}">${token.revoked_at ? 'Revoked' : 'Active · read only'}</span></td><td class="num">${escapeHtml(token.last_used_at || 'Not used')}</td><td style="text-align:right;">${token.revoked_at ? '' : `<button type="button" class="btn btn-ghost btn-sm btn-revoke-api-token" data-id="${token.id}" style="color:var(--bad);">Revoke</button>`}</td></tr>`).join('')}</tbody></table></div>` : '<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">No integration tokens created.</p>'}
        </section>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.getElementById('btn-create-api-token')?.addEventListener('click', () => {
      openModal({
        title: 'Create read-only API token',
        content: '<div class="field"><label for="api-token-name">Token name</label><input id="api-token-name" class="input" maxlength="64" placeholder="MCP reporting" required><div class="field-hint">Read-only access to project lists, visibility reports, CSV exports, and prompt research.</div></div>',
        confirmText: 'Create token',
        onConfirm: async () => {
          const name = document.getElementById('api-token-name')?.value.trim();
          if (!name) return false;
          try {
            const result = await settings.createApiToken(name);
            openModal({
              title: 'Copy your API token',
              showFooter: false,
              content: `<p style="margin:0 0 var(--sp-3);">This value will not be shown again.</p><textarea id="new-api-token" class="input" rows="3" readonly>${escapeHtml(result.token)}</textarea><div style="display:flex;justify-content:flex-end;margin-top:var(--sp-3);"><button type="button" id="btn-copy-api-token" class="btn btn-primary btn-sm">Copy token</button></div>`,
            });
            document.getElementById('btn-copy-api-token')?.addEventListener('click', async () => {
              const value = document.getElementById('new-api-token')?.value || '';
              try {
                await navigator.clipboard.writeText(value);
                toast.success('Token copied');
              } catch (err) {
                document.getElementById('new-api-token')?.select();
                toast.success('Select and copy the token');
              }
            });
            await ctx.reloadCurrentView();
            return true;
          } catch (err) {
            toast.error(t(err.error, {}, err.detail || 'Failed to create API token'));
            return false;
          }
        },
      });
    });

    document.querySelectorAll('.btn-revoke-api-token').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await settings.revokeApiToken(btn.getAttribute('data-id'));
          await ctx.reloadCurrentView();
          toast.success('API token revoked');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to revoke API token'));
        }
      });
    });

    document.getElementById('btn-add-custom-provider')?.addEventListener('click', () => {
      openModal({
        title: 'Add Custom Provider',
        content: customProviderForm(),
        confirmText: 'Test & Save',
        onConfirm: () => saveCustomProvider(ctx, 'Custom provider connected and saved'),
      });
    });

    document.querySelectorAll('.btn-edit-custom').forEach((btn) => {
      btn.addEventListener('click', () => {
        const provider = {
          name: btn.getAttribute('data-name'),
          base_url: btn.getAttribute('data-base-url'),
          model_id: btn.getAttribute('data-model-id'),
        };
        openModal({
          title: 'Edit Custom Provider',
          content: customProviderForm(provider),
          confirmText: 'Test & Save',
          onConfirm: () => saveCustomProvider(ctx, 'Custom provider connected and updated'),
        });
      });
    });

    document.querySelectorAll('.btn-del-custom').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await settings.deleteCustomProvider(btn.getAttribute('data-code'));
          await ctx.reloadCurrentView();
          toast.success('Custom provider removed');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to remove custom provider'));
        }
      });
    });

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
              await ctx.reloadCurrentView();
              toast.success(`${name} API key encrypted and saved`);
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
          await ctx.reloadCurrentView();
          toast.success('Key removed');
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to remove key'));
        }
      });
    });
  },
};
