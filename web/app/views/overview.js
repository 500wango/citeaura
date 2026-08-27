/**
 *  (Overview)
 */

import { projects } from '../api.js';
import { hasCatalogKey, t, tError } from '../i18n.js';
import { confirmModal } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { renderKpis } from '../components/kpi.js';
import { gradeBadge, samplingModeBadge, statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml } from '../safe-html.js';

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `
        <div class="app-view-container">
          ${renderEmpty({
            title: t('overview.no_project_title', {}, 'No Brand Selected'),
            description: t('overview.no_project_desc', {}, 'Create your first brand project to begin measuring AI search visibility.'),
            actionText: t('overview.add_brand_btn', {}, 'Add Brand'),
            actionRoute: 'onboarding',
          })}
        </div>
      `;
    }

    let report = null;
    let project = null;
    let tickets = [];
    let jobs = [];
    let visibilityPlan = null;

    try {
      [project, report, tickets, jobs, visibilityPlan] = await Promise.all([
        projects.get(projectId).catch(() => null),
        projects.getReport(projectId).catch(() => null),
        projects.getTickets(projectId).catch(() => []),
        projects.getJobs(projectId).catch(() => []),
        projects.getVisibilityPlan(projectId).catch(() => null),
      ]);
    } catch (err) {
      console.error('Failed to load overview data:', err);
    }

    if (!project) {
      return `<div class="app-view-container">${renderEmpty({
        title: t('overview.load_failed_title', {}, 'Could not load this brand'),
        description: t('overview.load_failed_desc', {}, 'The project record is unavailable. Retry or add a brand.'),
        actionText: t('overview.add_brand_btn', {}, 'Add Brand'),
        actionRoute: 'onboarding',
      })}</div>`;
    }

    const unmeasured = t('common.unmeasured', {}, 'Unmeasured');
    const mentionRate = report && report.mention_rate !== null && report.mention_rate !== undefined ? `${Math.round(report.mention_rate * 100)}%` : unmeasured;
    const overallGrade = report && report.grade;
    const totalTickets = Array.isArray(tickets) ? tickets.length : 0;
    const doneTickets = Array.isArray(tickets) ? tickets.filter((item) => item.status === 'done').length : 0;
    const engines = (report && report.engines) || [];
    const quality = (report && report.report_quality) || project.report_quality || {};
    const qualityIssues = Array.isArray(quality.issues) ? quality.issues : [];
    const readiness = quality.readiness || {};
    const questionReadiness = readiness.question || {};
    const attributionReadiness = readiness.attribution || {};
    const sentiment = project.insights?.sentiment || {};
    const sentimentBands = Array.isArray(sentiment.bands) ? sentiment.bands : [];
    const trend = (quality.measurement_quality && quality.measurement_quality.trend) || {};
    const trendNote = trend.status === 'noteworthy'
      ? `${trend.label || 'Trend'} ${trend.direction || ''} ${trend.delta_pp != null ? `${trend.delta_pp} pp` : ''}`.trim()
      : (trend.label || t('overview.trend_single', {}, 'Single-round observation; two comparable periods are required before calling a trend'));
    const measuredEngines = engines.filter((item) => item.sample_count);
    const plan = visibilityPlan?.plan || {};
    const baseline = visibilityPlan?.baseline;
    const phaseLabels = { baseline: 'Baseline', technical: 'Technical crawl', citation: 'Citation readiness', content: 'Content opportunities', offsite: 'Off-site entity', review: 'Review & re-measure' };
    const goals = Array.isArray(plan.goals) ? plan.goals : [];
    const priorityRank = { P0: 0, P1: 1, P2: 2 };
    const hasQuestions = Array.isArray(project.questions) && project.questions.length > 0;
    const projectStatus = project.project?.status || project.status;
    const activeJob = Array.isArray(jobs) ? jobs.find((job) => ['queued', 'running'].includes(job.status)) : null;
    const isGeneratingQuestions = !hasQuestions && (
      ['initializing', 'bootstrapping'].includes(projectStatus)
      || (Array.isArray(jobs) && jobs.some((job) => (
        ['bootstrap', 'autopilot'].includes(job.action) && ['queued', 'running'].includes(job.status)
      )))
    );
    const diagnosticReady = Boolean(quality.diagnostic_ready || quality.effective_report);
    const visibilityReady = Boolean(quality.measured_visibility || quality.measurement_baseline_ready);
    const implementationReady = Boolean(quality.implementation_ready);
    const firstValue = !diagnosticReady
      ? {
          label: t('overview.next_diagnostic_label', {}, 'Diagnostic in progress'),
          detail: t('overview.next_diagnostic_detail', {}, 'CiteAura is crawling the site and building the first action plan.'),
          route: activeJob ? 'overview' : (qualityIssues[0]?.route || 'siteaudit'),
          action: activeJob
            ? t('overview.next_diagnostic_action', {}, 'View job progress')
            : t('overview.action_next', {}, qualityIssues[0]?.action || 'Continue setup'),
        }
      : !visibilityReady
        ? {
            label: t('overview.next_visibility_label', {}, 'Diagnostic ready · AI visibility not measured'),
            detail: t('overview.next_visibility_detail', {}, 'Your technical findings and tickets are ready. Add BYOK or platform funding to measure AI answers.'),
            route: qualityIssues.find((item) => item.code === 'api_key_missing') ? 'engine-settings' : 'engines',
            action: t('overview.next_visibility_action', {}, qualityIssues.find((item) => item.code === 'api_key_missing')?.action || 'Open visibility matrix'),
          }
        : !implementationReady
          ? {
              label: t('overview.next_implementation_label', {}, 'Baseline ready · implementation review pending'),
              detail: t('overview.next_implementation_detail', {}, 'Review the highest-impact tickets and generated assets before deploying changes.'),
              route: 'plan',
              action: t('overview.next_implementation_action', {}, 'Open highest-impact tickets'),
            }
          : {
              label: t('overview.next_verify_label', {}, 'Implementation ready · verify the change'),
              detail: t('overview.next_verify_detail', {}, 'Run a closed-loop check to capture before/after evidence and prepare the client pack.'),
              route: 'verify',
              action: t('overview.next_verify_action', {}, 'Start verification'),
            };

    const kpiData = [
      { label: t('overview.kpi_mention_rate', {}, 'AI Mention Rate'), value: mentionRate, className: 'num', sub: trendNote },
      { label: t('overview.kpi_grade', {}, 'Technical Audit Grade'), value: overallGrade ? gradeBadge(overallGrade) : unmeasured },
      { label: t('overview.kpi_tickets', {}, 'Action Tickets'), value: `${doneTickets} / ${totalTickets}`, sub: t('overview.tickets_pending', { count: totalTickets - doneTickets }, `${totalTickets - doneTickets} pending`) },
      { label: t('overview.kpi_engines', {}, 'Measured Engines'), value: String(measuredEngines.length), sub: t('overview.engines_in_matrix', { count: engines.length }, `${engines.length} in matrix`) },
    ];

    return `
      <div class="app-view-container">
        <!-- View Header -->
        <div class="view-header">
          <div class="view-title-group">
            <div style="display:flex;align-items:center;gap:var(--sp-2);">
              <h1 class="view-title">${project.name || project.slug}</h1>
              ${overallGrade ? gradeBadge(overallGrade) : `<span class="tag tag-dim">${unmeasured}</span>`}
            </div>
            <div class="view-desc">
              <a href="${project.url}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:4px;color:var(--muted);text-decoration:none;">
                <span class="num">${project.url}</span>
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
              <span style="color:var(--faint);margin:0 var(--sp-2);">·</span>
              <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${t('common.market', {}, 'Market')}: ${project.market || 'Universal'}</span>
            </div>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-rerun-autopilot" class="btn btn-secondary btn-sm" ${activeJob ? 'disabled aria-busy="true"' : ''}>
              ${activeJob ? '<span class="spin"></span>' : ''}
              <span id="rerun-autopilot-label">${activeJob
                ? t('overview.pipeline_running', {}, 'Pipeline Running')
                : t('overview.action_rerun_autopilot', {}, 'Rerun Autopilot')}</span>
            </button>
            ${hasQuestions ? `
              <button type="button" id="btn-run-sample" class="btn btn-secondary btn-sm">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span>${t('overview.action_sample', {}, 'Run AI Sample')}</span>
              </button>` : isGeneratingQuestions ? `
              <button type="button" class="btn btn-secondary btn-sm" disabled aria-busy="true">
                <span class="spin"></span>
                <span>${t('overview.generating_questions', {}, 'Generating Questions...')}</span>
              </button>` : `
              <a href="#/questions" class="btn btn-secondary btn-sm">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>${t('questions.add_btn', {}, 'Add Target Questions')}</span>
              </a>`}
            <button type="button" id="btn-run-verify" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>${t('overview.action_verify', {}, 'Verify Changes')}</span>
            </button>
            <a href="#/${quality.effective_report ? 'report' : (qualityIssues[0]?.route || 'engines')}" class="btn btn-primary btn-sm">
              <span>${quality.effective_report
                ? t('overview.action_deliver', {}, 'View Delivery Pack')
                : t('overview.action_next', {}, qualityIssues[0]?.action || 'Continue setup')}</span>
            </a>
          </div>
        </div>

        <!-- Key Metrics Bar -->
        ${renderKpis(kpiData)}
        <div class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">AI Visibility Operating Plan</h3><p style="margin:3px 0 0;color:var(--muted);font-size:var(--fs-2);">${phaseLabels[plan.current_phase] || 'Baseline'} · ${plan.status || 'active'}</p></div>
            <button type="button" id="btn-capture-visibility-baseline" class="btn btn-secondary btn-sm">${baseline ? 'Refresh baseline' : 'Capture baseline'}</button>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-2);">
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">Phase</span><strong>${phaseLabels[plan.current_phase] || 'Baseline'}</strong></div>
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">Baseline</span><strong>${baseline ? new Date(baseline.captured_at).toLocaleDateString() : unmeasured}</strong></div>
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">Goals</span><strong>${goals.length || '—'}</strong></div>
          </div>
          ${goals.length ? `<div style="display:flex;flex-wrap:wrap;gap:var(--sp-2);">${goals.map((goal) => `<span class="tag tag-dim">${escapeHtml(goal.label || goal.type)} · ${goal.target}</span>`).join('')}</div>` : '<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">Set measurable goals to track progress across sampling cycles.</p>'}
        </div>
        <div class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.sentiment_context_title', {}, 'Brand sentiment context')}</h3><p style="margin:3px 0 0;color:var(--muted);font-size:var(--fs-2);">${t('overview.sentiment_context_desc', {}, 'Heuristic labels from unprompted answer replays; inspect evidence before reporting.')}</p></div>
            <span class="tag tag-dim">n=${Number(sentiment.sample_count || 0)}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:var(--sp-2);">${sentimentBands.map((band) => `<div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${escapeHtml(band.label)}</span><strong style="font-size:var(--fs-4);">${band.rate == null ? '—' : `${Math.round(band.rate * 100)}%`}</strong></div>`).join('')}</div>
        </div>
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;padding:var(--sp-4);border:1px solid var(--line);border-left:3px solid var(--brand);background:var(--deep);">
          <div style="display:flex;flex-direction:column;gap:4px;max-width:720px;">
            <strong style="font-size:var(--fs-3);">${escapeHtml(firstValue.label)}</strong>
            <span style="color:var(--muted);font-size:var(--fs-2);line-height:1.5;">${escapeHtml(firstValue.detail)}</span>
          </div>
          <a href="#/${firstValue.route}" class="btn btn-primary btn-sm">${escapeHtml(firstValue.action)} <span aria-hidden="true">→</span></a>
        </div>
        ${qualityIssues.length ? `
          <div class="card" style="gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${quality.effective_report
              ? t('overview.optional_upgrades', {}, 'Optional upgrades')
              : t('overview.next_steps', {}, 'Setup checklist')}</h3>
            ${qualityIssues.map((issue) => `
              <a href="#/${issue.route || 'overview'}" style="display:flex;justify-content:space-between;gap:var(--sp-3);text-decoration:none;">
                <span>${escapeHtml(issue.message)}</span>
                <span style="font-size:var(--fs-2);">${escapeHtml(issue.action || t('common.open', {}, 'Open'))} →</span>
              </a>
            `).join('')}
          </div>` : ''}

        <div class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('engines.evidence_readiness_title', {}, 'Evidence readiness')}</h3>
            <span class="tag ${quality.implementation_ready ? 'pill-good' : 'tag-dim'}">${quality.implementation_ready ? t('overview.implementation_ready', {}, 'Implementation ready') : t('overview.implementation_backlog', {}, 'Implementation backlog')}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-3);">
            ${[
              [t('overview.readiness_audit', {}, 'Audit'), readiness.audit?.label || t('overview.not_measured', {}, 'Not measured')],
              [t('overview.readiness_measurement', {}, 'Measurement baseline'), readiness.measurement?.label || quality.measurement_quality?.confidence?.label || t('overview.no_baseline', {}, 'No baseline')],
              [t('overview.readiness_questions', {}, 'Questions'), questionReadiness.label || t('overview.not_measured', {}, 'Not measured')],
              [t('overview.readiness_attribution', {}, 'Attribution'), attributionReadiness.label || t('overview.no_comparable', {}, 'No comparable period')],
            ].map(([label, value]) => `<div style="padding:var(--sp-3);border:1px solid var(--line);background:var(--page);border-radius:var(--r-md);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${escapeHtml(label)}</span><strong style="display:block;margin-top:4px;font-size:var(--fs-2);">${escapeHtml(value)}</strong></div>`).join('')}
          </div>
          ${questionReadiness.gaps?.length ? `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('overview.question_gaps', { count: questionReadiness.gaps.length }, `${questionReadiness.gaps.length} questions need additional comparable samples.`)} <a href="#/engines">${t('overview.fill_gaps', {}, 'Fill gaps')}</a></p>` : ''}
        </div>

        <!-- Core Modules Column -->
        <div style="display:grid;grid-template-columns:minmax(0, 7fr) minmax(0, 5fr);gap:var(--sp-6);">
          <!-- Left: Model Mention Rates & Sampling Modes -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.engines_visibility', {}, 'AI Engine Visibility Matrix')}</h3>
              <a href="#/engines" style="font-size:var(--fs-2);">${t('common.view_all', {}, 'View all')} →</a>
            </div>

            ${
              engines.length
                ? `
              <div style="display:flex;flex-direction:column;gap:var(--sp-3);">
                ${engines
                  .slice(0, 6)
                  .map(
                    (eng) => `
                  <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--sp-2) var(--sp-3);background:var(--page);border:1px solid var(--line);border-radius:var(--r-md);">
                    <div style="display:flex;flex-direction:column;gap:2px;">
                      <span style="font-weight:600;font-size:var(--fs-2);">${escapeHtml(eng.engine_name || eng.engine_code)}</span>
                      <div>${samplingModeBadge(eng.sampling_mode_code || eng.sampling_mode)}</div>
                    </div>
                    <div style="display:flex;align-items:center;gap:var(--sp-4);">
                      <div class="num" style="font-size:var(--fs-4);font-weight:700;color:var(--ink);">
                        ${eng.mention_rate !== null && eng.mention_rate !== undefined ? `${Math.round(eng.mention_rate * 100)}%` : unmeasured}
                      </div>
                    </div>
                  </div>
                `
                  )
                  .join('')}
              </div>
            `
                : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_engines_sampled', {}, 'No model sampling data recorded yet. Trigger a sample run to populate.')}</p>`
            }
          </div>

          <!-- Right: High-Priority Tickets -->
          <div class="card" style="gap:var(--sp-4);">
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.priority_tickets', {}, 'High-Impact Action Tickets')}</h3>
              <a href="#/plan" style="font-size:var(--fs-2);">${t('common.view_all', {}, 'View matrix')} →</a>
            </div>

            ${
              tickets && tickets.length
                ? `
              <div style="display:flex;flex-direction:column;gap:var(--sp-2);">
                ${tickets
                  .slice()
                  .sort((left, right) => (priorityRank[left.priority] ?? 99) - (priorityRank[right.priority] ?? 99))
                  .slice(0, 5)
                  .map((ticket) => {
                    const rawTitle = ticket.title_en || ticket.title || ticket.name || ticket.id;
                    const title = hasCatalogKey(ticket.title) ? t(ticket.title) : rawTitle;
                    return `
                  <a class="ticket-item" href="#/plan" style="text-decoration:none;">
                    <div style="display:flex;align-items:center;justify-content:space-between;">
                      <span class="ticket-item-title">${escapeHtml(title)}</span>
                      ${statusPill(ticket.status)}
                    </div>
                    <div class="ticket-item-meta">
                      <span>${t('common.priority', {}, 'Priority')}: <strong>${escapeHtml(ticket.priority || 'P1')}</strong></span>
                      <span>·</span>
                      <span>${t('common.effort', {}, 'Effort')}: <strong>${escapeHtml(ticket.effort || 'M')}</strong></span>
                    </div>
                  </a>
                `;
                  })
                  .join('')}
              </div>
            `
                : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_tickets', {}, 'No action tickets generated yet.')}</p>`
            }
          </div>
        </div>

        <!-- Pipeline Jobs History -->
        <div class="card" style="gap:var(--sp-3);">
          <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.pipeline_activity', {}, 'Pipeline Job History')}</h3>
          ${
            jobs && jobs.length
              ? `
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>${t('common.action', {}, 'Action')}</th>
                    <th>${t('common.status', {}, 'Status')}</th>
                    <th>${t('common.started_at', {}, 'Started')}</th>
                    <th>${t('common.duration', {}, 'Finished')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${jobs
                    .slice(0, 5)
                    .map(
                      (j) => `
                    <tr>
                      <td><span style="font-family:var(--font-mono);font-weight:600;">${j.action}</span></td>
                      <td>${statusPill(j.status)}</td>
                      <td class="num">${j.started_at ? new Date(j.started_at).toLocaleString() : '—'}</td>
                      <td class="num">${j.finished_at ? new Date(j.finished_at).toLocaleTimeString() : j.status === 'running' ? '<span class="spin"></span>' : '—'}</td>
                    </tr>
                  `
                    )
                    .join('')}
                </tbody>
              </table>
            </div>
          `
              : `<p style="color:var(--muted);font-size:var(--fs-2);">${t('overview.no_jobs', {}, 'No job runs recorded yet.')}</p>`
          }
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) return;

    const autopilotBtn = document.getElementById('btn-rerun-autopilot');
    const autopilotLabel = document.getElementById('rerun-autopilot-label');
    if (autopilotBtn && !autopilotBtn.disabled) {
      autopilotBtn.addEventListener('click', async () => {
        autopilotBtn.disabled = true;
        if (autopilotLabel) autopilotLabel.textContent = t('overview.autopilot_estimating', {}, 'Checking run estimate...');
        try {
          const estimate = await projects.estimateSample(projectId);
          const calls = Number(estimate?.estimate?.calls || 0);
          const minutes = Number(estimate?.estimate?.minutes || 0);
          const poolCostFen = Number(estimate?.estimate?.platform_pool_cost_cny_fen || 0);
          const estimateText = calls > 0
            ? t('overview.autopilot_estimate_calls', { calls, minutes: minutes || 0 }, `${calls} model calls, approximately ${minutes} minutes`)
            : t('overview.autopilot_estimate_none', {}, 'no billable model calls with the current provider configuration');
          const poolCostText = poolCostFen > 0
            ? t('overview.autopilot_pool_cost', { cost: (poolCostFen / 100).toFixed(2) }, ` Estimated CiteAura platform-pool cost: CNY ${(poolCostFen / 100).toFixed(2)}.`)
            : '';
          const confirmed = await confirmModal(
            t('overview.autopilot_confirm_body', { estimate: estimateText, pool: poolCostText }, `This will rerun the full 8-stage pipeline and refresh crawl data, AI samples, reports, assets, and the delivery pack. Manually maintained action tickets are preserved. Current estimate: ${estimateText}.${poolCostText} BYOK usage is billed directly by your model provider.`),
            {
              title: t('overview.autopilot_confirm_title', {}, 'Rerun Autopilot?'),
              confirmText: t('overview.autopilot_confirm_action', {}, 'Start Autopilot'),
            },
          );
          if (!confirmed) {
            autopilotBtn.disabled = false;
            if (autopilotLabel) autopilotLabel.textContent = t('overview.action_rerun_autopilot', {}, 'Rerun Autopilot');
            return;
          }

          if (autopilotLabel) autopilotLabel.textContent = t('overview.autopilot_starting', {}, 'Starting Autopilot...');
          const res = await projects.triggerAction(projectId, 'autopilot', { params: {} });
          toast.success(t('overview.autopilot_triggered', {}, 'Autopilot pipeline queued'));
          if (autopilotLabel) autopilotLabel.textContent = t('overview.pipeline_running', {}, 'Pipeline Running');
          ctx.pollActiveJobs();
          if (res?.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'autopilot', {
              projectId,
              onComplete: async () => {
                await ctx.reloadProjects();
                await ctx.reloadCurrentView();
              },
            });
          }
        } catch (err) {
          toast.error(tError(err));
          autopilotBtn.disabled = false;
          if (autopilotLabel) autopilotLabel.textContent = t('overview.action_rerun_autopilot', {}, 'Rerun Autopilot');
        }
      });
    }

    const sampleBtn = document.getElementById('btn-run-sample');
    if (sampleBtn) {
      sampleBtn.addEventListener('click', async () => {
        sampleBtn.disabled = true;
        try {
          const res = await projects.triggerSample(projectId);
          toast.success(t('overview.sample_triggered', {}, 'AI sampling task queued!'));
          ctx.pollActiveJobs();
          if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'sample');
          }
        } catch (err) {
          if (err.error === 'project_questions_required') {
            ctx.navigate('#/questions');
            return;
          }
          toast.error(tError(err));
        } finally {
          sampleBtn.disabled = false;
        }
      });
    }

    const verifyBtn = document.getElementById('btn-run-verify');
    if (verifyBtn) {
      verifyBtn.addEventListener('click', async () => {
        verifyBtn.disabled = true;
        try {
          const res = await projects.triggerVerify(projectId);
          toast.success(t('overview.verify_triggered', {}, 'Verification task queued!'));
          ctx.pollActiveJobs();
          if (res && res.job_id && typeof ctx.openTelemetry === 'function') {
            ctx.openTelemetry(res.job_id, 'verify');
          }
        } catch (err) {
          toast.error(tError(err));
        } finally {
          verifyBtn.disabled = false;
        }
      });
    }

    const baselineBtn = document.getElementById('btn-capture-visibility-baseline');
    if (baselineBtn) {
      baselineBtn.addEventListener('click', async () => {
        baselineBtn.disabled = true;
        try {
          await projects.captureVisibilityBaseline(projectId);
          toast.success('Visibility baseline captured');
          await ctx.reloadCurrentView();
        } catch (err) {
          toast.error(tError(err));
        } finally {
          baselineBtn.disabled = false;
        }
      });
    }
  },
};
