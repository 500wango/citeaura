/**
 *  (Plan & Playbook)
 */

import { analytics, projects } from '../api.js?v=3.5';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { openModal } from '../components/modal.js';
import { statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';
import { workspace } from '../api.js?v=3.5';

function localizedTicketField(ticket, field, enField, fallback = '') {
  const source = ticket?.[field] || ticket?.[enField] || fallback;
  if (!source) return '';
  return t(source, {}, ticket?.[enField] || source);
}

function ticketImpact(ticket) {
  const priority = String(ticket.priority || 'P1').toUpperCase();
  return priority === 'P2' ? 'low' : 'high';
}

function ticketEffortBand(ticket) {
  const effort = String(ticket.effort || 'M').toUpperCase();
  return effort === 'S' ? 'low' : 'high';
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    let tickets = [];
    try {
      const playbook = await projects.getPlaybook(projectId).catch(() => null);
      tickets = playbook?.playbook || await projects.getTickets(projectId).catch(() => []);
      if (!Array.isArray(tickets)) tickets = [];
    } catch (err) {
      console.error('Failed to load tickets:', err);
    }

    const currentMode = ctx.params.view || 'matrix';

    // Categorize four quadrants
    const quickWins = [];
    const strategic = [];
    const lowHanging = [];
    const deprioritize = [];

    tickets.forEach((item) => {
      const imp = ticketImpact(item);
      const eff = ticketEffortBand(item);

      if (imp === 'high' && eff === 'low') quickWins.push(item);
      else if (imp === 'high' && eff === 'high') strategic.push(item);
      else if (imp === 'low' && eff === 'low') lowHanging.push(item);
      else deprioritize.push(item);
    });

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('plan.title', {}, 'Engineering Action Tickets')}</h1>
            <p class="view-desc">
              ${t('plan.desc', {}, `${tickets.length} optimization tickets categorized by Priority × Effort.`)}
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
          <!-- 2x2 Matrix Mode -->
          <div class="matrix-grid">
            <!-- Quick Wins -->
            <div class="matrix-quadrant q-quick-wins">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--good);">${t('plan.q_quick_wins', {}, '1. Quick Wins (High Impact · Low Effort)')}</span>
                <span class="quadrant-count">${quickWins.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  quickWins.length
                    ? quickWins.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">${t('plan.no_tickets_in_quadrant', {}, 'No tickets in this quadrant')}</p>`
                }
              </div>
            </div>

            <!-- Strategic -->
            <div class="matrix-quadrant q-strategic">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--accent);">${t('plan.q_strategic', {}, '2. Strategic (High Impact · High Effort)')}</span>
                <span class="quadrant-count">${strategic.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  strategic.length
                    ? strategic.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">${t('plan.no_tickets_in_quadrant', {}, 'No tickets in this quadrant')}</p>`
                }
              </div>
            </div>

            <!-- Low-hanging -->
            <div class="matrix-quadrant q-low-hanging">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--warn);">${t('plan.q_low_hanging', {}, '3. Low-Hanging Fruit (Low Impact · Low Effort)')}</span>
                <span class="quadrant-count">${lowHanging.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  lowHanging.length
                    ? lowHanging.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">${t('plan.no_tickets_in_quadrant', {}, 'No tickets in this quadrant')}</p>`
                }
              </div>
            </div>

            <!-- Deprioritize -->
            <div class="matrix-quadrant q-deprioritize">
              <div class="quadrant-head">
                <span class="quadrant-title" style="color:var(--muted);">${t('plan.q_deprioritize', {}, '4. Deprioritize (Low Impact · High Effort)')}</span>
                <span class="quadrant-count">${deprioritize.length}</span>
              </div>
              <div class="quadrant-body">
                ${
                  deprioritize.length
                    ? deprioritize.map((ticket) => renderTicketCard(ticket)).join('')
                    : `<p style="color:var(--muted);font-size:12px;">${t('plan.no_tickets_in_quadrant', {}, 'No tickets in this quadrant')}</p>`
                }
              </div>
            </div>
          </div>
        `
            : `
          <!-- Table Mode -->
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
                      (ticket, idx) => {
                        const title = t(ticket.title, {}, ticket.title_en || ticket.title || ticket.name || ticket.id);
                        const role = t(ticket.owner || ticket.role, {}, ticket.owner_en || ticket.role || 'Engineering');
                        return `
                        <tr>
                          <td class="num" style="color:var(--muted);">${idx + 1}</td>
                          <td>
                            <strong style="font-size:var(--fs-2);color:var(--ink);">${escapeHtml(title)}</strong>
                            ${ticket.target_page ? `<div class="num" style="font-size:11px;color:var(--muted);">${escapeHtml(ticket.target_page)}</div>` : ''}
                          </td>
                          <td><span class="tag tag-neutral">${escapeHtml(role)}</span></td>
                          <td><span class="tag ${ticketImpact(ticket) === 'high' ? 'pill-good' : 'tag-dim'}">${escapeHtml(ticket.priority || 'P1')}</span></td>
                          <td><span class="tag ${ticketEffortBand(ticket) === 'low' ? 'pill-good' : 'tag-dim'}">${escapeHtml(ticket.effort || 'M')}</span></td>
                          <td>${statusPill(ticket.status)}</td>
                          <td style="text-align:right;">
                            <button type="button" class="btn btn-secondary btn-sm btn-edit-ticket" data-tid="${ticket.id}">
                              ${t('common.edit', {}, 'Edit')}
                            </button>
                          </td>
                        </tr>
                      `;
                      }
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

    // Bind ticket card clicks
    document.querySelectorAll('.ticket-item, .btn-edit-ticket').forEach((el) => {
      el.addEventListener('click', (e) => {
        const tid = el.getAttribute('data-tid');
        analytics.track('ticket_opened', { source: 'action_plan' });
        if (tid) showTicketDetailModal(projectId, tid, ctx);
      });
    });

    // Custom ticket modal
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
  const title = localizedTicketField(ticket, 'title', 'title_en', ticket.name || ticket.id);
  const role = localizedTicketField(ticket, 'owner', 'owner_en', ticket.role || t('plan.role_engineering', {}, 'Engineering'));
  return `
    <div class="ticket-item ${isDone ? 'is-done' : ''}" data-tid="${escapeHtml(ticket.id)}">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-2);">
        <span class="ticket-item-title">${escapeHtml(title)}</span>
        ${statusPill(ticket.status)}
      </div>
      <div class="ticket-item-meta">
        <span class="tag tag-dim" style="font-size:10px;">${escapeHtml(role)}</span>
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

  const title = localizedTicketField(ticket, 'title', 'title_en', ticket.name || ticket.id);
  const why = localizedTicketField(ticket, 'why', 'why_en', ticket.desc_en || ticket.desc || ticket.description || '');
  const action = localizedTicketField(ticket, 'action', 'action_en');
  const role = localizedTicketField(ticket, 'owner', 'owner_en', ticket.role_en || ticket.role || t('plan.role_engineering', {}, 'Engineering'));
  const acceptance = localizedTicketField(ticket.acceptance || {}, 'desc', 'desc_en');
  const notes = Array.isArray(ticket.notes)
    ? ticket.notes.map((item) => item?.text || item?.note || '').filter(Boolean).join('\n')
    : (ticket.note || '');

  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-4);">
      <div>
        <h4 style="font-size:var(--fs-4);font-weight:700;margin:0 0 var(--sp-1) 0;">${escapeHtml(title)}</h4>
        <p style="color:var(--muted);font-size:var(--fs-2);margin:0;"><strong>${t('plan.why_label', {}, 'Why:')}</strong> ${escapeHtml(why || t('plan.no_rationale', {}, 'No rationale recorded.'))}</p>
        ${action ? `<div style="margin-top:var(--sp-2);padding:var(--sp-2) var(--sp-3);background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);font-size:var(--fs-1);color:var(--ink);"><strong style="color:var(--accent);">${t('plan.action_label', {}, 'Action:')}</strong> ${escapeHtml(action)}</div>` : ''}
        ${acceptance ? `<div style="margin-top:var(--sp-1);font-size:var(--fs-2);"><strong>${t('plan.acceptance_label', {}, 'Acceptance:')}</strong> ${escapeHtml(acceptance)} ${ticket.acceptance?.type ? `(${escapeHtml(ticket.acceptance.type)})` : ''}</div>` : ''}
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-3);">
        <div class="field" style="margin:0;">
          <label>${t('plan.col_status', {}, 'Status')}</label>
          <select id="edit-ticket-status" class="input">
            <option value="todo" ${ticket.status === 'todo' ? 'selected' : ''}>${t('plan.status_todo', {}, 'To Do')}</option>
            <option value="doing" ${ticket.status === 'doing' ? 'selected' : ''}>${t('plan.status_doing', {}, 'In Progress')}</option>
            <option value="done" ${ticket.status === 'done' ? 'selected' : ''}>${t('plan.status_done', {}, 'Done / Completed')}</option>
            <option value="blocked" ${ticket.status === 'blocked' ? 'selected' : ''}>${t('plan.status_blocked', {}, 'Blocked')}</option>
            <option value="wontfix" ${ticket.status === 'wontfix' ? 'selected' : ''}>${t('plan.status_wontfix', {}, "Won't fix")}</option>
          </select>
        </div>
        <div class="field" style="margin:0;">
          <label>${t('plan.col_role', {}, 'Role')}</label>
          <input type="text" class="input" value="${role}" disabled>
        </div>
      </div>

      <div class="field" style="margin:0;">
        <label>${t('plan.notes_label', {}, 'Implementation Notes')}</label>
        <textarea id="edit-ticket-notes" class="input" rows="3" placeholder="Add a new implementation note...">${escapeHtml(notes)}</textarea>
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
        await ctx.reloadCurrentView();
        return true;
      } catch (err) {
        toast.error(tError(err));
        return false;
      }
    },
  });
}

async function showCreateTicketModal(projectId, ctx) {
  const questions = await workspace.getQuestions(projectId).catch(() => []);
  const questionOptions = (Array.isArray(questions) ? questions : []).map((question) => {
    const id = question.id || '';
    const text = question.text || question.question || question.query || id;
    return `<label style="display:flex;gap:var(--sp-2);align-items:flex-start;font-size:var(--fs-2);">
      <input type="checkbox" name="influenced-question" value="${escapeHtml(id)}">
      <span><span class="num">${escapeHtml(id)}</span> ${escapeHtml(text)}</span>
    </label>`;
  }).join('');
  const content = `
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
      <div class="field" style="margin:0;">
        <label>${t('plan.target_page_label', {}, 'Target URL / Page')} *</label>
        <input type="url" id="new-t-url" class="input" placeholder="https://example.com/review" required>
      </div>
      <div class="field" style="margin:0;">
        <label>${t('plan.create_title_label', {}, 'Requested Update')} *</label>
        <textarea id="new-t-ask" class="input" rows="3" placeholder="Describe the factual change requested from the page owner" required></textarea>
      </div>
      <div class="field" style="margin:0;">
        <label>${t('plan.influenced_questions_label', {}, 'Influenced questions')} *</label>
        <div id="new-t-questions" style="max-height:180px;overflow:auto;display:flex;flex-direction:column;gap:var(--sp-2);">${questionOptions || `<span style="color:var(--muted);">${t('plan.add_questions_first', {}, 'Add questions first.')}</span>`}</div>
      </div>
    </div>
  `;

  openModal({
    title: t('plan.create_custom_ticket', {}, 'Create Action Ticket'),
    content,
    confirmText: t('common.create', {}, 'Create Ticket'),
    onConfirm: async () => {
      const url = document.getElementById('new-t-url')?.value.trim();
      const ask_text = document.getElementById('new-t-ask')?.value.trim();
      const influenced_questions = Array.from(document.querySelectorAll('input[name="influenced-question"]:checked'))
        .map((input) => input.value)
        .filter(Boolean);

      if (!url || !ask_text || !influenced_questions.length) return false;

      try {
        await projects.createTicket(projectId, { url, ask_text, influenced_questions });
        toast.success(t('plan.ticket_created_success', {}, 'Ticket created successfully'));
        await ctx.reloadCurrentView();
        return true;
      } catch (err) {
        toast.error(tError(err));
        return false;
      }
    },
  });
}
