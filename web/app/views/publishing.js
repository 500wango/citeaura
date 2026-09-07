/**
 *  (Publishing Destinations)
 */

import { publishing, workspace, projects } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

let publisherState = [];
let projectState = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function selectedPaths() {
  return [...document.querySelectorAll('[data-github-asset]:checked')]
    .map((input) => input.value)
    .filter(Boolean);
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let state = {};
    let prs = [];
    let project = null;
    let assets = [];
    let prsUnavailable = false;
    const refreshPrs = Boolean(ctx.params?.refresh);
    const [publisherResult, prResult, projectResult, assetResult] = await Promise.allSettled([
      publishing.get(projectId),
      publishing.listGithubPrs(projectId, refreshPrs),
      projects.get(projectId),
      workspace.getAssets(projectId),
    ]);
    if (publisherResult.status === 'fulfilled') state = publisherResult.value;
    if (prResult.status === 'fulfilled') prs = prResult.value.prs || [];
    else prsUnavailable = true;
    if (projectResult.status === 'fulfilled') project = projectResult.value;
    if (assetResult.status === 'fulfilled') assets = assetResult.value;
    publisherState = Array.isArray(state.publishers) ? state.publishers : [];
    projectState = project;
    const github = publisherState.find((item) => item.code === 'github');
    const deployableAssets = (Array.isArray(assets) ? assets : [])
      .filter((item) => item?.status === 'deployable' && item?.path);

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('publishing.title', {}, 'Publishing Destinations')}</h1>
            <p class="view-desc">
              ${t('publishing.desc', {}, 'Push structured optimization content into connected channels as drafts for editorial review.')}
            </p>
          </div>
        </div>


        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(300px, 1fr));gap:var(--sp-6);">
          ${publisherState.map((publisher) => {
            const name = publisher.name_en || t(publisher.name, {}, publisher.name || publisher.code);
            const note = publisher.note_en || t(publisher.note, {}, publisher.note || '');
            return `
            <div class="card" style="gap:var(--sp-4);">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);">
                <strong style="font-size:var(--fs-4);">${name}</strong>
                <span class="tag ${publisher.ready ? 'pill-good' : 'tag-dim'}">
                  ${publisher.ready ? t('common.ready', {}, 'Ready') : t('publishing.setup_required', {}, 'Setup required')}
                </span>
              </div>
              <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">${note}</p>
              ${publisher.missing?.length ? `<div class="field-hint">Missing: ${publisher.missing.join(', ')}</div>` : ''}
              <div style="display:flex;align-items:center;gap:var(--sp-2);">
                <button type="button" class="btn btn-secondary btn-sm btn-config-publisher" data-code="${publisher.code}">
                  ${t('publishing.config_btn', {}, 'Configure Destination')}
                </button>
                <span title="${t('publishing.tip_body', {}, 'Keep credentials in the encrypted settings fields. Never append secrets to a URL query string.')}" style="cursor:help;color:var(--muted);display:inline-flex;align-items:center;">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                </span>
              </div>
            </div>
            `;
          }).join('')}
        </div>
        ${github?.ready ? `<section class="card" style="margin-top:var(--sp-6);">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:var(--sp-4);">
            <div>
              <h2 style="margin:0;font-size:var(--fs-4);">Create GitHub review request</h2>
              <p style="margin:var(--sp-1) 0 0;color:var(--muted);">Select approved assets. CiteAura creates a branch and pull request; nothing is merged automatically.</p>
            </div>
            <button type="button" class="btn btn-primary btn-sm" id="btn-create-github-pr" ${deployableAssets.length ? '' : 'disabled'}>Create pull request</button>
          </div>
          ${deployableAssets.length ? `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--sp-2);margin-top:var(--sp-4);">
            ${deployableAssets.map((asset) => `<label style="display:flex;align-items:flex-start;gap:var(--sp-2);padding:var(--sp-3);border:1px solid var(--line);border-radius:var(--r-sm);cursor:pointer;">
              <input type="checkbox" data-github-asset value="assets/${escapeHtml(asset.path)}">
              <span><strong style="display:block;overflow-wrap:anywhere;">${escapeHtml(asset.path)}</strong><span class="field-hint">Ready to publish</span></span>
            </label>`).join('')}
          </div>` : `<p style="margin:var(--sp-4) 0 0;color:var(--muted);">No approved assets are available. Review required assets in Campaigns & Assets before creating a pull request.</p>`}
        </section>` : ''}
        <section class="card" style="margin-top:var(--sp-6);">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:var(--sp-3);">
            <div><h2 style="margin:0;font-size:var(--fs-4);">GitHub review queue</h2><p style="margin:var(--sp-1) 0 0;color:var(--muted);">Reviewable PRs never merge or deploy automatically.</p></div>
            <button type="button" class="btn btn-secondary btn-sm" id="btn-refresh-github-prs">Refresh status</button>
          </div>
          ${prsUnavailable ? '<p style="margin:var(--sp-3) 0 0;color:var(--danger);">GitHub PR status is unavailable. Refresh to retry.</p>' : (prs.length ? `<div class="tbl" style="overflow-x:auto;margin-top:var(--sp-3);"><table class="table"><thead><tr><th>Ticket</th><th>Run</th><th>Status</th><th>PR</th></tr></thead><tbody>${prs.map((pr) => `<tr><td>${pr.ticket_id || ''}</td><td>${pr.run_id || ''}</td><td><span class="tag ${pr.status === 'merged' ? 'pill-good' : 'tag-dim'}">${pr.status || 'open'}</span></td><td><a href="${pr.url || '#'}" target="_blank" rel="noopener noreferrer">Open PR</a></td></tr>`).join('')}</tbody></table></div>` : '<p style="margin:var(--sp-3) 0 0;color:var(--muted);">No GitHub PRs yet. Create one from an approved asset and ticket.</p>')}
        </section>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-refresh-github-prs')?.addEventListener('click', () => ctx.navigate(`#/publishing?refresh=${Date.now()}`));
    document.getElementById('btn-create-github-pr')?.addEventListener('click', () => {
      const paths = selectedPaths();
      if (!paths.length) {
        toast.error('Select at least one approved asset');
        return;
      }
      showGithubPrModal(projectId, paths, ctx);
    });
    document.querySelectorAll('.btn-config-publisher').forEach((button) => {
      button.addEventListener('click', () => {
        const publisher = publisherState.find((item) => item.code === button.getAttribute('data-code'));
        if (publisher) showPublisherModal(projectId, publisher, ctx);
      });
    });
  },
};

function showPublisherModal(projectId, publisher, ctx) {
  const name = publisher.name_en || t(publisher.name, {}, publisher.name || publisher.code);
  const configFields = Array.isArray(publisher.cfg) ? publisher.cfg : [];
  const credentialFields = Array.isArray(publisher.env) ? publisher.env : [];
  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      ${configFields.map((field, index) => {
        const isGithubDirectory = publisher.code === 'github' && field.key === 'dir';
        const label = isGithubDirectory ? 'Repository directory (optional)' : field.key;
        const hint = isGithubDirectory
          ? 'Leave blank for the repository root. For example, docs/geo writes selected assets to docs/geo/.'
          : field.hint_en || field.hint || '';
        return `
        <div class="field" style="margin:0;">
          <label>${escapeHtml(label)}</label>
          <input type="text" id="publisher-config-${index}" class="input" value="${escapeHtml(field.value || '')}" placeholder="${escapeHtml(hint)}">
        </div>
      `;
      }).join('')}
      ${credentialFields.map((name, index) => `
        <div class="field" style="margin:0;">
          <label>${escapeHtml(name)}</label>
          <input type="password" id="publisher-credential-${index}" class="input" autocomplete="new-password" placeholder="Leave blank to keep the saved credential">
        </div>
      `).join('')}
      ${!configFields.length && !credentialFields.length ? '<p>No configuration is required.</p>' : ''}
      <div style="background:var(--page);border:1px solid var(--line);border-radius:var(--r-md);padding:var(--sp-3);font-size:var(--fs-1);color:var(--muted);display:flex;gap:var(--sp-2);align-items:flex-start;margin-top:var(--sp-1);">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:2px;color:var(--brand);"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        <div>
          <strong style="color:var(--ink);">${t('publishing.tip_title', {}, 'Authentication & Security Tip')}</strong>
          <div style="margin-top:2px;line-height:1.4;">
            ${t('publishing.tip_body', {}, 'Keep credentials in the encrypted settings fields. Never append secrets to a URL query string; query strings can be stored in browser and proxy logs.')}
          </div>
        </div>
      </div>
    </div>
  `;

  openModal({
    title: `Configure ${name}`,
    content,
    confirmText: t('common.save', {}, 'Save Settings'),
    onConfirm: async () => {
      const config = Object.fromEntries(configFields.map((field, index) => [
        field.key,
        document.getElementById(`publisher-config-${index}`)?.value.trim() || '',
      ]));
      const credentials = {};
      credentialFields.forEach((name, index) => {
        const value = document.getElementById(`publisher-credential-${index}`)?.value.trim();
        if (value) credentials[name] = value;
      });

      try {
        await publishing.save(projectId, publisher.code, { config, credentials });
        toast.success(t('publishing.saved_success', {}, 'Publishing settings saved'));
        ctx.navigate(`#/publishing?updated=${Date.now()}`);
        return true;
      } catch (err) {
        toast.error(tError(err));
        return false;
      }
    },
  });
}

function showGithubPrModal(projectId, paths, ctx) {
  const defaultTicket = projectState?.tasks?.find((item) => item?.status !== 'done')?.id || 'ASSET';
  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <p style="margin:0;color:var(--muted);">${paths.length} approved asset${paths.length === 1 ? '' : 's'} will be committed to a new branch and submitted for review.</p>
      <div class="field" style="margin:0;"><label for="github-pr-ticket">Ticket ID</label><input id="github-pr-ticket" class="input" value="${escapeHtml(defaultTicket)}" maxlength="128"></div>
      <div class="field" style="margin:0;"><label for="github-pr-title">Pull request title</label><input id="github-pr-title" class="input" value="CiteAura: ${escapeHtml(projectState?.name || projectState?.slug || 'assets')}" maxlength="300"></div>
      <div class="field" style="margin:0;"><label for="github-pr-criteria">Review notes <span style="color:var(--muted);font-weight:400;">(optional)</span></label><textarea id="github-pr-criteria" class="input" rows="4" maxlength="5000" placeholder="What should the reviewer verify before merging?"></textarea></div>
      <div role="alert" id="github-pr-error" style="display:none;color:var(--danger);"></div>
    </div>
  `;
  openModal({
    title: 'Create GitHub pull request',
    content,
    confirmText: 'Create pull request',
    onConfirm: async () => {
      const ticketId = document.getElementById('github-pr-ticket')?.value.trim() || '';
      const title = document.getElementById('github-pr-title')?.value.trim() || '';
      const acceptanceCriteria = document.getElementById('github-pr-criteria')?.value.trim() || '';
      const error = document.getElementById('github-pr-error');
      if (!ticketId) {
        error.textContent = 'Enter a ticket ID to name the review branch.';
        error.style.display = 'block';
        return false;
      }
      try {
        const result = await publishing.createGithubPr(projectId, {
          ticket_id: ticketId,
          run_id: `assets-${Date.now()}`,
          paths,
          title,
          acceptance_criteria: acceptanceCriteria || null,
          confirmed: true,
        });
        toast.success(`Pull request #${result.number} created`);
        ctx.navigate(`#/publishing?updated=${Date.now()}`);
        return true;
      } catch (err) {
        error.textContent = tError(err);
        error.style.display = 'block';
        return false;
      }
    },
  });
}
