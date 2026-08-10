/**
 * 即插即用部署资产视图 (Assets & LLMs.txt)
 */

import { workspace } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let assetsData = {};
    try {
      assetsData = await workspace.getAssets(projectId).catch(() => ({}));
    } catch (e) {}

    const llmsTxt = assetsData.llms_txt || `# CiteAura Official Knowledge Index\n> Make Your Brand the Default Answer in AI Search\n\n## Overview\nCiteAura is the next-generation Generative Engine Optimization (GEO) platform.\n\n## Core Facts\n- Product: CiteAura GEO Platform\n- Pricing: 14-day free trial, Starter from $79/mo\n- Technology: Multi-model sampling across DeepSeek, ChatGPT, Claude, Gemini, GLM\n`;
    const jsonLd =
      assetsData.jsonld ||
      JSON.stringify(
        {
          '@context': 'https://schema.org',
          '@type': 'SoftwareApplication',
          name: 'CiteAura',
          applicationCategory: 'BusinessApplication',
          operatingSystem: 'Web',
          offers: {
            '@type': 'Offer',
            price: '79',
            priceCurrency: 'USD',
          },
        },
        null,
        2
      );

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('assets.title', {}, 'Ready-to-Deploy GEO Assets')}</h1>
            <p class="view-desc">
              ${t('assets.desc', {}, 'Pre-generated structured data, /llms.txt knowledge indices, and extraction blocks with explicit placement guidance.')}
            </p>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:var(--sp-6);">
          <!-- 01: /llms.txt -->
          <div class="card" style="gap:var(--sp-3);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <div>
                <strong style="font-size:var(--fs-4);">1. /llms.txt Knowledge Index</strong>
                <span class="tag tag-accent" style="margin-left:var(--sp-2);">Target: /llms.txt</span>
              </div>
              <button type="button" class="btn btn-secondary btn-sm btn-copy" data-target="code-llms">
                ${t('common.copy', {}, 'Copy Text')}
              </button>
            </div>
            <div class="code-box">
              <pre id="code-llms">${llmsTxt}</pre>
            </div>
            <div style="font-size:12px;color:var(--muted);">
              <strong>Placement:</strong> Deploy directly at the root of your domain (e.g. <code>https://yourdomain.com/llms.txt</code>).
            </div>
          </div>

          <!-- 02: JSON-LD -->
          <div class="card" style="gap:var(--sp-3);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <div>
                <strong style="font-size:var(--fs-4);">2. JSON-LD Structured Data</strong>
                <span class="tag tag-accent" style="margin-left:var(--sp-2);">Target: &lt;head&gt;</span>
              </div>
              <button type="button" class="btn btn-secondary btn-sm btn-copy" data-target="code-jsonld">
                ${t('common.copy', {}, 'Copy Code')}
              </button>
            </div>
            <div class="code-box">
              <pre id="code-jsonld">&lt;script type="application/ld+json"&gt;\n${jsonLd}\n&lt;/script&gt;</pre>
            </div>
            <div style="font-size:12px;color:var(--muted);">
              <strong>Placement:</strong> Insert into the <code>&lt;head&gt;</code> tag of your homepage and core product landing pages.
            </div>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.querySelectorAll('.btn-copy').forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-target');
        const text = document.getElementById(targetId)?.textContent || '';
        navigator.clipboard.writeText(text).then(() => {
          toast.success(t('common.copied', {}, 'Copied to clipboard!'));
        });
      });
    });
  },
};
