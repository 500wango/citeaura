/**
 * 行动工单矩阵视图 (Plan & Playbook)
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let tickets = [];
    try {
      tickets = await projects.getTickets(projectId).catch(() => []);
      if (!Array.isArray(tickets)) tickets = [];
    } catch (err) {
      console.error('Failed to load tickets:', err);
    }

    const currentMode = ctx.params.view || 'matrix';

    // 分类四个象限
    const quickWins = [];
    const strategic = [];
    const lowHanging = [];
    const deprioritize = [];

    tickets.forEach((t) => {
      const imp = String(t.impact || 'high').toLowerCase();
      const eff = String(t.effort || 'low').toLowerCase();

      if (imp === 'high' && eff === 'low') quickWins.push(t);
      else if (imp === 'high' && eff === 'high') strategic.push(t);
      else if (imp === 'low' && eff === 'low') lowHanging.push(t);
      else deprioritize.push(t);
    });

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('plan.title', {}, 'Engineering Action Tickets')}</h1>
            <p class="view-desc">
              ${t('plan.desc', {}, '13 standardized optimization tickets categorized by Impact × Effort to maximize engineering ROI and close recommendation gaps.')}
            </p>
          </div>
          <div class="view-actions">
            <div class="seg">
              <a href="#/plan?view=matrix" class="seg-opt ${currentMode === 'matrix' ? 'is-active' : ''}">${t('plan.mode_matrix', {}, '2×2 Matrix')}</a>
              <a href="#/plan?view=table" class="seg-opt ${currentMode === 'table' ? 'is-active' : ''}">${t('plan.mode_table', {}, 'Table List')}</a>
            </div>
            <button type="button" id="btn-create-custom-ticket" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('plan.create_ticket_btn', {}, 'Create Ticket')}</span>
            </button>
          </div>
        </div>

        ${
          currentMode === 'matrix'
            ? `
          <!-- 2x2 矩阵模式 -->
          <div class="matrix-grid">
            <!-- 快速见效 Quick Wins -->
            <div class="matrix-quadrant q-quick-wins">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--good);">${t('plan.q_quick_wins', {}, '1. Quick Wins (High Impact · Low Effort)')}</span>
                <span class="quadrant-count">${quickWins.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  quickWins.length
                    ? quickWins.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">No tickets in this quadrant</p>`
                }
              </div>
            </div>

            <!-- 战略深耕 Strategic -->
            <div class="matrix-quadrant q-strategic">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--accent);">${t('plan.q_strategic', {}, '2. Strategic (High Impact · High Effort)')}</span>
                <span class="quadrant-count">${strategic.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  strategic.length
                    ? strategic.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">No tickets in this quadrant</p>`
                }
              </div>
            </div>

            <!-- 顺手修复 Low-hanging -->
            <div class="matrix-quadrant q-low-hanging">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--warn);">${t('plan.q_low_hanging', {}, '3. Low-Hanging Fruit (Low Impact · Low Effort)')}</span>
                <span class="quadrant-count">${lowHanging.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  lowHanging.length
                    ? lowHanging.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">No tickets in this quadrant</p>`
                }
              </div>
            </div>

            <!-- 暂缓处理 Deprioritize -->
            <div class="matrix-quadrant q-deprioritize">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--muted);">${t('plan.q_deprioritize', {}, '4. Deprioritize (Low Impact · High Effort)')}</span>
                <span class="quadrant-count">${deprioritize.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  deprioritize.length
                    ? deprioritize.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">No tickets in this quadrant</p>`
                }
              </div>
            </div>
          </div>
        `
            : `
          <!-- 表格模式 -->
          <div class="card" style="padding:0;overflow:hidden;">
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>${t('plan.col_title', {}, 'Ticket Title')}</th>
                    <th>${t('plan.col_role', {}, 'Assignee Role')}</th>
                    <th>${t('plan.col_impact', {}, 'Impact')}</th>
                    <th>${t('plan.col_effort', {}, 'Effort')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                    <th style="text-align:right;">${t('common.action', {}, 'Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${tickets
                    .map(
                      (ticket, idx) => `
                    <tr>
                      <td class="num" style="color:var(--muted);">${idx + 1}</td>
                      <td>
                        <strong style="font-size:var(--fs-2);color:var(--ink);">${ticket.title || ticket.name || ticket.id}</strong>
                        ${ticket.target_page ? `<div class="num" style="font-size:11px;color:var(--muted);">${ticket.target_page}</div>` : ''}
                      </td>
                      <td><span class="tag tag-neutral">${ticket.role || 'Engineering'}</span></td>
                      <td><span class="tag ${ticket.impact === 'High' ? 'pill-good' : 'tag-dim'}">${ticket.impact || 'High'}</span></td>
                      <td><span class="tag ${ticket.effort === 'Low' ? 'pill-good' : 'tag-dim'}">${ticket.effort || 'Low'}</span></td>
                      <td>${statusPill(ticket.status)}</td>
                      <td style="text-align:right;">
                        <button type="button" class="btn btn-secondary btn-sm btn-edit-ticket" data-tid="${ticket.id}">
                          ${t('common.edit', {}, 'Edit')}
                        </button>
                      </td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          </div>
        `
        }
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    // 绑定工单卡片点击
    document.querySelectorAll('.ticket-item, .btn-edit-ticket').forEach((el) => {
      el.addEventListener('click', (e) => {
        const tid = el.getAttribute('data-tid');
        if (tid) showTicketDetailModal(projectId, tid, ctx);
      });
    });

    // 自定义工单
    const customBtn = document.getElementById('btn-create-custom-ticket');
    if (customBtn) {
      customBtn.addEventListener('click', () => {
        showCreateTicketModal(projectId, ctx);
      });
    }
  },
};

function renderTicketCard(ticket) {
  const isDone = ticket.status === 'done';
  return `
    <div class="ticket-item ${isDone ? 'is-done' : ''}" data-tid="${ticket.id}">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-2);">
        <span class="ticket-item-title">${ticket.title || ticket.name || ticket.id}</span>
        ${statusPill(ticket.status)}
      </div>
      <div class="ticket-item-meta">
        <span class="tag tag-dim" style="font-size:10px;">${ticket.role || 'Engineering'}</span>
        ${ticket.target_page ? `<span class="num" style="max-width:18ch;overflow:hidden;text-overflow:ellipsis;">${ticket.target_page}</span>` : ''}
      </div>
    </div>
  `;
}

async function showTicketDetailModal(projectId, tid, ctx) {
  let tickets = [];
  try {
    tickets = await projects.getTickets(projectId);
  } catch (e) {}

  const ticket = tickets.find((t) => String(t.id) === String(tid)) || { id: tid };

  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
      <div>
        <h4 style="font-size:var(--fs-4);font-weight:700;margin:0 0 var(--sp-1) 0;">${ticket.title || ticket.name || ticket.id}</h4>
        <p style="color:var(--muted);font-size:var(--fs-2);margin:0;">${ticket.desc || ticket.description || 'Actionable engineering implementation item.'}</p>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-3);">
        <div class="field" style="margin:0;">
          <label>${t('plan.col_status', {}, 'Status')}</label>
          <select id="edit-ticket-status" class="input">
            <option value="todo" ${ticket.status === 'todo' ? 'selected' : ''}>To Do</option>
            <option value="doing" ${ticket.status === 'doing' ? 'selected' : ''}>In Progress</option>
            <option value="done" ${ticket.status === 'done' ? 'selected' : ''}>Done / Completed</option>
          </select>
        </div>
        <div class="field" style="margin:0;">
          <label>${t('plan.col_role', {}, 'Role')}</label>
          <input type="text" class="input" value="${ticket.role || 'Engineering'}" disabled>
        </div>
      </div>

      <div class="field" style="margin:0;">
        <label>${t('plan.notes_label', {}, 'Implementation Notes')}</label>
        <textarea id="edit-ticket-notes" class="input" rows="3" placeholder="Deployment details, PR links, or verification observations...">${ticket.note || ticket.notes || ''}</textarea>
      </div>
    </div>
  `;

  openModal({
    title: t('plan.ticket_details', {}, 'Ticket Details'),
    content,
    confirmText: t('common.save', {}, 'Save Changes'),
    onConfirm: async () => {
      const status = document.getElementById('edit-ticket-status')?.value;
      const note = document.getElementById('edit-ticket-notes')?.value;

      try {
        await projects.patchTicket(projectId, tid, { status, note });
        toast.success(t('plan.ticket_saved', {}, 'Ticket updated'));
        ctx.navigate('#/plan');
        return true;
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to update ticket'));
        return false;
      }
    },
  });
}

function showCreateTicketModal(projectId, ctx) {
  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <div class="field" style="margin:0;">
        <label>${t('plan.create_title_label', {}, 'Ticket Title')} *</label>
        <input type="text" id="new-t-title" class="input" placeholder="e.g. Optimize JSON-LD Product schema on pricing page" required>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-3);">
        <div class="field" style="margin:0;">
          <label>${t('plan.col_impact', {}, 'Impact')}</label>
          <select id="new-t-impact" class="input">
            <option value="High">High</option>
            <option value="Low">Low</option>
          </select>
        </div>
        <div class="field" style="margin:0;">
          <label>${t('plan.col_effort', {}, 'Effort')}</label>
          <select id="new-t-effort" class="input">
            <option value="Low">Low</option>
            <option value="High">High</option>
          </select>
        </div>
      </div>
      <div class="field" style="margin:0;">
        <label>${t('plan.target_page_label', {}, 'Target URL / Page')}</label>
        <input type="text" id="new-t-page" class="input" placeholder="/pricing">
      </div>
    </div>
  `;

  openModal({
    title: t('plan.create_custom_ticket', {}, 'Create Action Ticket'),
    content,
    confirmText: t('common.create', {}, 'Create Ticket'),
    onConfirm: async () => {
      const title = document.getElementById('new-t-title')?.value.trim();
      const impact = document.getElementById('new-t-impact')?.value;
      const effort = document.getElementById('new-t-effort')?.value;
      const target_page = document.getElementById('new-t-page')?.value.trim();

      if (!title) return false;

      try {
        await projects.createTicket(projectId, { title, impact, effort, target_page, status: 'todo' });
        toast.success(t('plan.ticket_created_success', {}, 'Ticket created successfully'));
        ctx.navigate('#/plan');
        return true;
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to create ticket'));
        return false;
      }
    },
  });
}
