/**
 *  (Automation & Schedule)
 */

import { projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let schedule = {};
    try {
      schedule = await projects.getSchedule(projectId).catch(() => ({}));
    } catch (e) {}

    const enabled = Boolean(schedule.enabled);
    const intervalDays = [7, 14, 30].includes(schedule.interval_days) ? schedule.interval_days : 7;

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('automation.title', {}, 'Automated Matrix Monitoring')}</h1>
            <p class="view-desc">
              ${t('automation.desc', {}, 'Configure scheduled background cycles to re-crawl, re-run sampling, and refresh reports. Verification remains a separate explicit step.')}
            </p>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-save-schedule" class="btn btn-primary btn-sm">
              <span>${t('common.save_changes', {}, 'Save Schedule')}</span>
            </button>
          </div>
        </div>

        <div class="card" style="max-width:680px;gap:var(--sp-4);">
          <div class="card" style="background:var(--page);padding:var(--sp-4);border-radius:var(--r-md);">
            <label style="display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;">
              <input type="checkbox" id="schedule-enabled" ${enabled ? 'checked' : ''} style="margin-top:2px;">
              <div style="font-size:var(--fs-2);">
                <strong style="color:var(--ink);">${t('automation.enable_title', {}, 'Enable automated periodic monitoring')}</strong>
                <div style="color:var(--muted);margin-top:2px;">
                  ${t('automation.enable_desc', {}, 'CiteAura background workers will automatically execute crawl, audit, sampling, and report runs on this schedule.')}
                </div>
              </div>
            </label>
          </div>

          <div class="field" style="margin:0;">
            <label>${t('automation.interval_label', {}, 'Monitoring Recurrence Interval')}</label>
            <select id="schedule-interval" class="input">
              <option value="7" ${intervalDays === 7 ? 'selected' : ''}>Weekly (7 Days)</option>
              <option value="14" ${intervalDays === 14 ? 'selected' : ''}>Bi-Weekly (14 Days)</option>
              <option value="30" ${intervalDays === 30 ? 'selected' : ''}>Monthly (30 Days)</option>
            </select>
          </div>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    document.getElementById('btn-save-schedule')?.addEventListener('click', async () => {
      const enabled = document.getElementById('schedule-enabled')?.checked;
      const interval_days = parseInt(document.getElementById('schedule-interval')?.value || '7');

      try {
        await projects.updateSchedule(projectId, { enabled, interval_days });
        toast.success(t('automation.saved_success', {}, 'Schedule updated successfully'));
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to update schedule'));
      }
    });
  },
};
