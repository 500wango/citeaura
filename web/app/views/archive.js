/**
 *  (Archive & Snapshots)
 */

import { archive } from '../api.js?v=3.4';
import { t, tError } from '../i18n.js';
import { escapeHtml } from '../safe-html.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let archives = [];
    try {
      archives = await archive.list(projectId).catch(() => []);
    } catch (e) {}

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('archive.title', {}, 'Project Snapshots & Backup Archives')}</h1>
            <p class="view-desc">
              ${t('archive.desc', {}, 'Create immutable point-in-time snapshots of workspace files, tickets, and sample history.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-create-snapshot" class="btn btn-primary btn-sm">
              + ${t('archive.create_btn', {}, 'Create Snapshot')}
            </button>
          </div>
        </div>

        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('archive.snapshots_list', {}, 'Historical Snapshots')}</h3>
            <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${archives.length} snapshots</span>
          </div>

          ${
            archives.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('archive.col_id', {}, 'Snapshot ID')}</th>
                    <th>${t('archive.col_note', {}, 'Note')}</th>
                    <th>${t('archive.col_files', {}, 'Files')}</th>
                    <th>${t('common.created_at', {}, 'Created')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${archives
                    .map(
                      (a) => `
                    <tr>
                      <td><span class="num" style="font-weight:700;">${a.id}</span></td>
                      <td>${a.note || 'Manual snapshot'}</td>
                      <td class="num">${a.file_count || '—'}</td>
                      <td class="num">${new Date(a.created_at).toLocaleString()}</td>
                      <td style="text-align:right;">
                        <button type="button" class="btn btn-secondary btn-sm btn-restore-snap" data-id="${a.id}">
                          ${t('archive.restore_btn', {}, 'Restore')}
                        </button>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<div style="padding:var(--sp-8);text-align:center;color:var(--muted);font-size:var(--fs-2);">
                ${renderEmpty({
                  title: t('archive.no_snapshots', {}, 'No Snapshots Found'),
                  description: t('archive.no_snapshots_desc', {}, 'Create point-in-time project snapshots before executing major ticket changes.'),
                  actionText: t('archive.create_btn', {}, 'Create Snapshot'),
                  onAction: () => document.getElementById('btn-create-snapshot')?.click(),
                })}
              </div>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-create-snapshot')?.addEventListener('click', () => {
      openModal({
        title: t('archive.create_modal_title', {}, 'Create Project Snapshot'),
        content: `
          <div class="field" style="margin:0;">
            <label>${t('archive.note_label', {}, 'Snapshot Note / Description')}</label>
            <input type="text" id="snap-note" class="input" placeholder="e.g. Baseline before Q3 re-architecture">
          </div>
        `,
        confirmText: t('archive.create_btn', {}, 'Create Snapshot'),
        onConfirm: async () => {
          const note = document.getElementById('snap-note')?.value.trim();
          try {
            await archive.create(projectId, note);
            toast.success(t('archive.create_success', {}, 'Snapshot created successfully'));
            ctx.navigate('#/archive');
            return true;
          } catch (err) {
            toast.error(tError(err));
            return false;
          }
        },
      });
    });

    document.querySelectorAll('.btn-restore-snap').forEach((btn) => {
      btn.addEventListener('click', () => {
        const snapId = btn.getAttribute('data-id');
        openModal({
          title: t('archive.restore_modal_title', {}, 'Confirm Snapshot Restoration'),
          content: `
            <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
              <div class="banner warn">
                ${escapeHtml(t('archive.restore_warning', { id: snapId }, `Warning: Restoring this snapshot will overwrite current project workspace files with data from ${snapId}.`))}
              </div>
              <div class="field" style="margin-top:var(--sp-2);">
                <label>${t('archive.restore_type_label', { phrase: `RESTORE ${snapId}` }, `Type RESTORE ${snapId} to confirm:`)}</label>
                <input type="text" id="confirm-restore-text" class="input" placeholder="RESTORE ${escapeHtml(snapId)}">
              </div>
            </div>
          `,
          confirmText: t('archive.restore_btn', {}, 'Restore'),
          isDanger: true,
          onConfirm: async () => {
            const val = document.getElementById('confirm-restore-text')?.value.trim();
            if (val !== `RESTORE ${snapId}`) {
              toast.error(t('archive.restore_mismatch', {}, 'Confirmation text does not match'));
              return false;
            }

            try {
              await archive.restore(projectId, snapId, val);
              toast.success(t('archive.restore_success', {}, 'Project restored successfully'));
              ctx.navigate('#/overview');
              return true;
            } catch (err) {
              toast.error(tError(err));
              return false;
            }
          },
        });
      });
    });
  },
};
