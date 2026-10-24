/**
 *  (Overview)
 */

import { projects } from '../api.js';
import { hasCatalogKey, issueText, t, tError, ticketField, translateBackendLabel } from '../i18n.js';
import { confirmModal } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { renderKpis } from '../components/kpi.js';
import { gradeBadge, samplingModeBadge, samplingModeLabel, statusPill } from '../components/badge.js';
import { renderEmpty } from '../components/empty.js';
import { escapeHtml, safeHttpUrl } from '../safe-html.js';

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
    let citationSources = null;
    let citationFeatures = null;

    try {
      [project, report, tickets, jobs, visibilityPlan, citationSources, citationFeatures] = await Promise.all([
        projects.get(projectId).catch(() => null),
        projects.getReport(projectId).catch(() => null),
        projects.getTickets(projectId).catch(() => []),
        projects.getJobs(projectId).catch(() => []),
        projects.getVisibilityPlan(projectId).catch(() => null),
        projects.getCitationSources(projectId).catch(() => null),
        projects.getCitationFeatures(projectId).catch(() => ({ overview: false })),
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
    const measurementQuality = quality.measurement_quality || {};
    const currentSamples = measurementQuality.current || {};
    const measurementConfidence = quality.confidence || measurementQuality.confidence || {};
    const userSummary = (report && report.user_summary) || {};
    const summaryScope = userSummary.evidence_scope || {};
    const summaryFinding = userSummary.primary_finding || {};
    const qualityIssues = Array.isArray(quality.issues) ? quality.issues : [];
    const summaryIssue = qualityIssues.find((item) => item.code === summaryFinding.code) || qualityIssues[0] || null;
    const summaryHeadline = summaryIssue
      ? issueText(summaryIssue)
      : (summaryScope.measured
        ? t('report.summary_measured_title', {}, 'AI visibility has been measured')
        : t('report.summary_ready_title', {}, 'Your diagnostic is ready to review'));
    const summaryWhy = summaryIssue
      ? t('report.summary_why_primary', {}, 'Review the highest-priority finding before interpreting visibility results.')
      : t('report.summary_why_default', {}, 'Use the evidence and action plan to decide what to improve first.');
    const summaryAction = summaryIssue
      ? issueText(summaryIssue, 'action')
      : t('report.review_action', {}, 'Review the action plan');
    const summaryLimitations = qualityIssues
      .filter((item) => item !== summaryIssue && ['info', 'warning'].includes(item.severity))
      .slice(0, 3)
      .map((item) => issueText(item));
    const readiness = quality.readiness || {};
    const questionReadiness = readiness.question || {};
    const attributionReadiness = readiness.attribution || {};
    const sentiment = project.insights?.sentiment || {};
    const sentimentBands = Array.isArray(sentiment.bands) ? sentiment.bands : [];
    const trend = (quality.measurement_quality && quality.measurement_quality.trend) || {};
    const trendLabel = trend.label ? escapeHtml(translateBackendLabel(trend.label)) : '';
    const trendNote = trend.status === 'noteworthy'
      ? `${trendLabel || 'Trend'} ${escapeHtml(trend.direction || '')} ${trend.delta_pp != null ? `${escapeHtml(trend.delta_pp)} pp` : ''}`.trim()
      : (trendLabel || t('overview.trend_single', {}, 'Single-round observation; two comparable periods are required before calling a trend'));
    const measuredEngines = engines.filter((item) => item.sample_count);
    const eligibleSamples = Number(report?.sample_count || currentSamples.successful || 0);
    const provenance = (report && report.provenance) || {};
    const questionSet = provenance.question_set || {};
    const providerNames = [...new Set(measuredEngines.map((item) => (
      item.provider_name || item.engine_name || item.engine_code
    )).filter(Boolean))];
    const measuredModes = [...new Set(measuredEngines.map((item) => item.sampling_mode).filter(Boolean))];
    const reportDate = report?.date || (report?.sample_artifact ? String(report.sample_artifact) : '');
    const visibilityMeasured = eligibleSamples > 0 && measuredEngines.length > 0;
    const mentionRateKnown = report && report.mention_rate !== null && report.mention_rate !== undefined;
    const cohortReason = !visibilityMeasured
      ? (issueText(qualityIssues.find((item) => item.code === 'sampling_missing'))
        || t('overview.cohort_none', {}, 'No eligible cohort yet. Run a labeled sample to make this measurable.'))
      : (!mentionRateKnown
        ? t('overview.cohort_mixed_modes', {}, 'Sampling modes are shown separately; no combined mention rate is reported.')
        : '');
    const plan = visibilityPlan?.plan || {};
    const baseline = visibilityPlan?.baseline;
    const phaseLabels = {
      baseline: t('overview.phase_baseline', {}, 'Baseline'),
      technical: t('overview.phase_technical', {}, 'Technical crawl'),
      citation: t('overview.phase_citation', {}, 'Citation readiness'),
      content: t('overview.phase_content', {}, 'Content opportunities'),
      offsite: t('overview.phase_offsite', {}, 'Off-site entity'),
      review: t('overview.phase_review', {}, 'Review & re-measure'),
    };
    const goals = Array.isArray(plan.goals) ? plan.goals : [];
    const priorityRank = { P0: 0, P1: 1, P2: 2 };
    const quickWins = (Array.isArray(tickets) ? tickets : [])
      .filter((item) => item.status !== 'done' && String(item.priority || 'P1').toUpperCase() !== 'P2' && String(item.effort || 'M').toUpperCase() === 'S')
      .sort((left, right) => (priorityRank[left.priority] ?? 99) - (priorityRank[right.priority] ?? 99))
      .slice(0, 5);
    const hasQuestions = Array.isArray(project.questions) && project.questions.length > 0;
    const projectStatus = project.project?.status || project.status;
    // Only http(s) URLs may reach href; a bare domain still gets a usable link.
    const rawProjectUrl = String(project.url || '');
    const projectUrl = safeHttpUrl(rawProjectUrl)
      || (/^[\w.-]+\.[a-z]{2,}(?:[/?#].*)?$/i.test(rawProjectUrl) ? safeHttpUrl(`https://${rawProjectUrl}`) : '');
    const activeJob = Array.isArray(jobs) ? jobs.find((job) => ['queued', 'running'].includes(job.status)) : null;
    const isViewer = ctx.role === 'viewer';
    const actionBlockReason = isViewer
      ? t('plan.viewer_read_only', {}, 'Viewer access: you can inspect evidence but cannot change tickets or plans.')
      : t('project_job_already_running', {}, 'A job is already running for this brand.');
    const isGeneratingQuestions = !hasQuestions && (
      ['initializing', 'bootstrapping'].includes(projectStatus)
      || (Array.isArray(jobs) && jobs.some((job) => (
        ['bootstrap', 'autopilot'].includes(job.action) && ['queued', 'running'].includes(job.status)
      )))
    );
    const diagnosticReady = Boolean(quality.diagnostic_ready || quality.effective_report);
    const visibilityReady = Boolean(quality.measured_visibility || quality.measurement_baseline_ready);
    const implementationReady = Boolean(quality.implementation_ready);
    // 健康条只能展示真实审计结果；未采集的维度明确标注 unmeasured，
    // 不能把所有维度写死成告警。
    const audit = (report && report.audit) || {};
    const siteHealth = audit.site || {};
    const crawlMeasured = Number(audit.page_count || siteHealth.pages_crawled || 0) > 0;
    const crawlOk = crawlMeasured && Number(siteHealth.pages_ok || 0) > 0;
    // 页面级审计只覆盖抓取样本；分母必须一并展示，否则读数会被当成全站结论。
    const crawlCoverage = siteHealth.coverage || {};
    const discoveredUrls = Number(crawlCoverage.discovered_urls || 0);
    const crawledPages = Number(crawlCoverage.crawled_pages || siteHealth.pages_crawled || audit.page_count || 0);
    const coverageRatio = Number(crawlCoverage.ratio);
    const coverageSuffix = crawlCoverage.discovered_is_partial ? '+' : '';
    const crawlScopeNote = crawlMeasured
      ? (discoveredUrls
        ? t('overview.crawl_scope_sitemap', {
          crawled: crawledPages,
          discovered: `${discoveredUrls}${coverageSuffix}`,
        }, `Crawled ${crawledPages}/${discoveredUrls}${coverageSuffix} sitemap URLs`)
          + (Number.isFinite(coverageRatio)
            ? ` (${t('overview.crawl_scope_percent', { percent: Math.round(coverageRatio * 100), mode: crawlCoverage.mode || 'sampled' }, `${Math.round(coverageRatio * 100)}%, ${crawlCoverage.mode || 'sampled'} crawl`)})`
            : '')
        : t('overview.crawl_scope_internal', { count: crawledPages }, `Crawled ${crawledPages} pages from internal links (no sitemap discovered)`))
      : t('overview.crawl_scope_none', {}, 'No measured crawl result');
    const robotsMeasured = crawlMeasured && Object.prototype.hasOwnProperty.call(siteHealth, 'ai_bots_blocked');
    const robotsOk = robotsMeasured && !(siteHealth.ai_bots_blocked || []).length;
    const llmsMeasured = typeof siteHealth.has_llms_txt === 'boolean';
    const llmsOk = llmsMeasured && Boolean(siteHealth.has_llms_txt);
    const brandFacts = report && report.insights ? report.insights.brand_facts : undefined;
    const brandFactsMeasured = brandFacts !== undefined && brandFacts !== null;
    const brandFactsOk = brandFactsMeasured
      && String(brandFacts).toLowerCase() !== 'missing'
      && !(brandFacts && typeof brandFacts === 'object' && brandFacts.status === 'missing');
    const healthIndicator = (label, measured, ok, title) => (
      `<span class="health-indicator ${measured && ok ? 'is-ok' : 'is-warn'}" title="${escapeHtml(title)}">`
      + `<span class="status-dot"></span>${escapeHtml(label)}${measured ? '' : ` ${escapeHtml(t('common.unmeasured', {}, 'Unmeasured'))}`}</span>`
    );
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
      {
        label: t('overview.kpi_mention_rate', {}, 'AI Mention Rate'),
        value: mentionRate,
        className: 'num',
        state: mentionRateKnown ? 'measured' : 'unmeasured',
        sub: trendNote,
        meta: mentionRateKnown || visibilityMeasured
          ? t('overview.kpi_denominator', { count: eligibleSamples }, `${eligibleSamples} eligible samples`)
          : t('overview.cohort_none_short', {}, 'No eligible samples'),
        title: t('overview.kpi_mention_detail', {}, 'Share of successful, eligible answers that mention the brand. Brand-named probe questions are excluded.'),
      },
      { label: t('overview.kpi_grade', {}, 'Technical Audit Grade'), value: overallGrade ? gradeBadge(overallGrade) : unmeasured },
      { label: t('overview.kpi_tickets', {}, 'Action Tickets'), value: `${doneTickets} / ${totalTickets}`, sub: t('overview.tickets_pending', { count: totalTickets - doneTickets }, `${totalTickets - doneTickets} pending`) },
      { label: t('overview.kpi_engines', {}, 'Measured Engines'), value: String(measuredEngines.length), sub: t('overview.engines_in_matrix', { count: engines.length }, `${engines.length} in matrix`), state: measuredEngines.length ? 'measured' : 'unmeasured' },
    ];

    const cohortBar = `
      <section class="cohort-bar" aria-label="${t('overview.cohort_title', {}, 'Measurement cohort')}">
        <div class="cohort-bar-main">
          <div class="cohort-bar-title">
            <span>${t('overview.cohort_title', {}, 'Measurement cohort')}</span>
            ${visibilityMeasured
              ? measuredModes.map((mode) => samplingModeBadge(mode)).join('')
              : `<span class="tag tag-dim">${unmeasured}</span>`}
          </div>
          <dl>
            <div><dt>${t('overview.cohort_question_set', {}, 'Question set')}</dt><dd>${escapeHtml(questionSet.version || report?.question_set_version || '—')}${questionSet.count ? ` · ${Number(questionSet.count)} ${t('overview.cohort_questions', {}, 'questions')}` : ''}</dd></div>
            <div><dt>${t('overview.cohort_providers', {}, 'Providers')}</dt><dd>${providerNames.length ? escapeHtml(providerNames.join(', ')) : '—'}</dd></div>
            <div><dt>${t('overview.cohort_mode', {}, 'Sampling mode')}</dt><dd>${measuredModes.length ? escapeHtml(measuredModes.map((mode) => samplingModeLabel(mode)).join(' · ')) : '—'}</dd></div>
            <div><dt>${t('overview.cohort_window', {}, 'Window')}</dt><dd>${escapeHtml(reportDate || '—')}</dd></div>
            <div><dt>${t('overview.cohort_eligible', {}, 'Eligible samples')}</dt><dd class="num">${eligibleSamples || '—'}</dd></div>
          </dl>
          ${cohortReason ? `<p class="cohort-bar-note">${escapeHtml(cohortReason)}</p>` : ''}
        </div>
        <div class="cohort-bar-action">
          <a href="#/${visibilityMeasured ? 'engines' : (measurementConfidence && !measurementConfidence.sufficient ? 'engine-settings' : 'engines')}" class="btn btn-secondary btn-sm">
            ${visibilityMeasured ? t('overview.cohort_inspect', {}, 'Inspect cohort') : t('overview.cohort_configure', {}, 'Configure sampling')}
          </a>
        </div>
      </section>
    `;

    return `
      <div class="app-view-container">
        <!-- View Header -->
        <div class="view-header">
          <div class="view-title-group">
            <div style="display:flex;align-items:center;gap:var(--sp-2);">
              <h1 class="view-title">${escapeHtml(project.name || project.slug || '')}</h1>
              ${overallGrade ? gradeBadge(overallGrade) : `<span class="tag tag-dim">${unmeasured}</span>`}
            </div>
            <div class="view-desc">
              ${projectUrl ? `<a href="${escapeHtml(projectUrl)}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:4px;color:var(--muted);text-decoration:none;">
                <span class="num">${escapeHtml(project.url)}</span>
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>` : `<span class="num">${escapeHtml(project.url || '')}</span>`}
              <span style="color:var(--faint);margin:0 var(--sp-2);">·</span>
              <span style="font-family:var(--font-mono);font-size:var(--fs-1);color:var(--muted);">${t('common.market', {}, 'Market')}: ${escapeHtml(project.market || t('overview.universal_market', {}, 'Universal'))}</span>
            </div>
          </div>
          <div class="view-actions">
            <button type="button" id="btn-rerun-autopilot" class="btn btn-secondary btn-sm" ${(activeJob || isViewer) ? `disabled ${activeJob ? 'aria-busy="true"' : ''} title="${escapeHtml(actionBlockReason)}"` : ''}>
              ${activeJob ? '<span class="spin"></span>' : ''}
              <span id="rerun-autopilot-label">${activeJob
                ? t('overview.pipeline_running', {}, 'Pipeline Running')
                : t('overview.action_rerun_autopilot', {}, 'Rerun Autopilot')}</span>
            </button>
            ${hasQuestions ? `
              <button type="button" id="btn-run-sample" class="btn btn-secondary btn-sm" ${(activeJob || isViewer) ? `disabled title="${escapeHtml(actionBlockReason)}"` : ''}>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span>${t('overview.action_sample', {}, 'Fill Sample Gaps')}</span>
              </button>` : isGeneratingQuestions ? `
              <button type="button" class="btn btn-secondary btn-sm" disabled aria-busy="true">
                <span class="spin"></span>
                <span>${t('overview.generating_questions', {}, 'Generating Questions...')}</span>
              </button>` : `
              <a href="#/questions" class="btn btn-secondary btn-sm">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>${t('questions.add_btn', {}, 'Add Target Questions')}</span>
              </a>`}
            <button type="button" id="btn-run-verify" class="btn btn-secondary btn-sm" ${(activeJob || isViewer) ? `disabled title="${escapeHtml(actionBlockReason)}"` : ''}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>${t('overview.action_verify', {}, 'Verify Changes')}</span>
            </button>
            <a href="#/report" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              <span>${t('nav.report', {}, 'Client Delivery Packs')}</span>
            </a>
            <a href="#/${escapeHtml(quality.effective_report ? 'report' : (qualityIssues[0]?.route || 'engines'))}" class="btn btn-primary btn-sm">
              <span>${quality.effective_report
                ? t('overview.action_deliver', {}, 'View Delivery Pack')
                : t('overview.action_next', {}, qualityIssues[0]?.action || 'Continue setup')}</span>
            </a>
          </div>
        </div>

        ${isViewer ? `<div class="read-only-note" role="status">${escapeHtml(actionBlockReason)}</div>` : ''}
        ${activeJob ? `<div class="job-block-note" role="status"><span class="status-dot"></span>${escapeHtml(t('project_job_already_running', {}, 'A job is already running for this brand.'))} ${escapeHtml(activeJob.action || '')} · ${escapeHtml(activeJob.status || '')}</div>` : ''}
        ${cohortBar}

        <!-- Better Stack 6-Dimension Health Lights & Telemetry Bar -->
        <div class="health-strip-card" style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);padding:10px 16px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
            <span style="font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:var(--muted);">${t('overview.evidence_checks', {}, 'Evidence checks')}</span>
            ${healthIndicator('robots.txt', robotsMeasured, robotsOk, robotsMeasured ? t('overview.robots_checked', {}, 'robots.txt checked by the last crawl') : t('overview.robots_unmeasured', {}, 'No measured robots.txt result'))}
            ${healthIndicator('llms.txt', llmsMeasured, llmsOk, llmsMeasured ? t('overview.llms_checked', {}, 'llms.txt checked by the last crawl') : t('overview.llms_unmeasured', {}, 'No measured llms.txt result'))}
            ${healthIndicator(t('overview.brand_facts', {}, 'Brand facts'), brandFactsMeasured, brandFactsOk, brandFactsMeasured ? t('overview.facts_checked', {}, 'Brand facts extracted from sampled answers') : t('overview.facts_unmeasured', {}, 'No measured brand facts result'))}
            ${healthIndicator(t('overview.crawl', {}, 'Crawl'), crawlMeasured, crawlOk, crawlScopeNote)}
            ${healthIndicator(t('overview.kpi_mention_rate', {}, 'AI Mention Rate'), visibilityMeasured, visibilityMeasured, visibilityMeasured ? t('overview.eligible_sample_meta', { count: eligibleSamples }, `${eligibleSamples} eligible samples`) : t('overview.no_eligible_samples', {}, 'No eligible samples'))}
          </div>
          <span class="demo-provenance-pill" style="font-family:var(--font-mono);font-size:10px;padding:2px 8px;border-radius:12px;background:var(--deep);border:1px solid var(--line);color:var(--muted);">
            ${visibilityMeasured ? t('overview.cohort_traceable', {}, 'Traceable to a labeled cohort') : unmeasured}
          </span>
        </div>

        <!-- Key Metrics Bar -->
        <section class="card overview-user-summary" style="gap:var(--sp-3);border-left:3px solid var(--accent);">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;">
            <div style="min-width:0;max-width:760px;">
              <span class="kicker">${t('overview.current_summary', {}, 'Current summary')}</span>
              <h2 style="font-size:var(--fs-5);line-height:1.3;margin:var(--sp-1) 0 0;">${escapeHtml(summaryHeadline)}</h2>
              <p style="margin:var(--sp-2) 0 0;color:var(--ink-2);line-height:1.5;">${escapeHtml(summaryWhy)}</p>
            </div>
            <a href="#/${escapeHtml(summaryIssue?.route || userSummary.next_route || 'plan')}" class="btn btn-primary btn-sm">${escapeHtml(summaryAction || t('overview.action_next', {}, 'Review next action'))}<span aria-hidden="true"> →</span></a>
          </div>
          <div style="display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap;color:var(--muted);font-size:var(--fs-2);">
            <span>${summaryScope.measured ? t('overview.summary_measured', {}, 'Measured evidence') : t('overview.summary_unmeasured', {}, 'Visibility not measured')}</span>
            <span aria-hidden="true">·</span>
            <span>${t('overview.summary_samples', { count: Number(summaryScope.sample_count || 0) }, `${Number(summaryScope.sample_count || 0)} samples`)}</span>
            ${summaryScope.confidence ? `<span aria-hidden="true">·</span><span>${escapeHtml(translateBackendLabel(summaryScope.confidence))}</span>` : ''}
            ${summaryFinding.ticket_id ? `<span aria-hidden="true">·</span><span>${t('overview.summary_ticket', {}, 'Linked action ticket')} ${escapeHtml(summaryFinding.ticket_id)}</span>` : ''}
          </div>
          ${summaryLimitations.length ? `<div style="font-size:var(--fs-2);color:var(--muted);">${escapeHtml(summaryLimitations[0])}</div>` : ''}
        </section>
        ${renderKpis(kpiData)}
        ${citationFeatures?.overview ? `<div class="card" style="gap:var(--sp-3);"><div style="display:flex;justify-content:space-between;align-items:center;gap:var(--sp-3);"><div><h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.citation_intelligence_title', {}, 'Citation Source Intelligence')}</h3><p style="margin:3px 0 0;color:var(--muted);font-size:var(--fs-2);">${t('overview.citation_intelligence_desc', {}, 'Latest web-enabled evidence, traceable to a sampling run.')}</p></div><a href="#/channels" class="btn btn-secondary btn-sm">${t('overview.view_channels', {}, 'View Channels')}</a></div>${citationSources?.status === 'measured' ? `<div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;">${(citationSources.domains || []).slice(0,5).map((item) => `<span class="tag tag-neutral">${escapeHtml(item.domain)} · ${(item.share * 100).toFixed(1)}%</span>`).join('')}</div><span style="color:var(--muted);font-size:var(--fs-1);">${citationSources.total_citations} ${t('overview.citations_count', {}, 'citations')} · ${escapeHtml(citationSources.run_id || '')}</span>` : `<span style="color:var(--muted);">${t('channels.unmeasured_run_sample', {}, 'Unmeasured · Run a sample')}</span>`}</div>` : ''}
        <div class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('overview.operating_plan_title', {}, 'AI Visibility Operating Plan')}</h3><p style="margin:3px 0 0;color:var(--muted);font-size:var(--fs-2);">${phaseLabels[plan.current_phase] || phaseLabels.baseline} · ${escapeHtml(plan.status || 'active')}</p></div>
            <button type="button" id="btn-capture-visibility-baseline" class="btn btn-secondary btn-sm" ${isViewer ? `disabled title="${escapeHtml(actionBlockReason)}"` : ''}>${baseline ? t('overview.refresh_baseline', {}, 'Refresh baseline') : t('overview.capture_baseline', {}, 'Capture baseline')}</button>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-2);">
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('overview.phase_label', {}, 'Phase')}</span><strong>${phaseLabels[plan.current_phase] || phaseLabels.baseline}</strong></div>
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('overview.baseline_label', {}, 'Baseline')}</span><strong>${baseline ? new Date(baseline.captured_at).toLocaleDateString() : unmeasured}</strong></div>
            <div style="padding:var(--sp-3);background:var(--page);border:1px solid var(--line);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('overview.goals_label', {}, 'Goals')}</span><strong>${goals.length || '—'}</strong></div>
          </div>
          ${goals.length ? `<div style="display:flex;flex-wrap:wrap;gap:var(--sp-2);">${goals.map((goal) => `<span class="tag tag-dim">${escapeHtml(goal.label || goal.type)} · ${escapeHtml(goal.target)}</span>`).join('')}</div>` : `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('overview.set_goals', {}, 'Set measurable goals to track progress across sampling cycles.')}</p>`}
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
          <a href="#/${escapeHtml(firstValue.route)}" class="btn btn-primary btn-sm">${escapeHtml(firstValue.action)} <span aria-hidden="true">→</span></a>
        </div>
        ${qualityIssues.length ? `
          <div class="card" style="gap:var(--sp-3);">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${quality.effective_report
              ? t('overview.optional_upgrades', {}, 'Optional upgrades')
              : t('overview.next_steps', {}, 'Setup checklist')}</h3>
            ${qualityIssues.map((issue) => `
              <a href="#/${escapeHtml(issue.route || 'overview')}" style="display:flex;justify-content:space-between;gap:var(--sp-3);text-decoration:none;">
                <span>${escapeHtml(issueText(issue))}</span>
                <span style="font-size:var(--fs-2);">${escapeHtml(issueText(issue, 'action') || t('common.open', {}, 'Open'))} →</span>
              </a>
            `).join('')}
          </div>` : ''}

        <details class="card" style="gap:var(--sp-3);" open>
          <summary style="cursor:pointer;font-size:var(--fs-4);font-weight:600;">${t('overview.quick_wins_title', {}, 'This week: quick wins')} <span style="color:var(--muted);font-size:var(--fs-2);font-weight:400;">${t('overview.quick_wins_desc', {}, 'High-impact actions with a small effort estimate')}</span></summary>
          ${quickWins.length ? `<div style="display:flex;flex-direction:column;gap:var(--sp-2);margin-top:var(--sp-2);">${quickWins.map((ticket) => `<a href="#/plan" style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);padding:var(--sp-3);border:1px solid var(--line);background:var(--page);text-decoration:none;"><span><strong style="display:block;font-size:var(--fs-2);">${escapeHtml(ticket.title || ticket.name || ticket.id)}</strong><span style="display:block;color:var(--muted);font-size:var(--fs-1);margin-top:3px;">${escapeHtml(ticket.action || ticket.why || t('overview.review_action_ticket', {}, 'Review the linked action ticket'))}</span></span><span class="tag pill-warn">${escapeHtml(ticket.priority || 'P1')} · ${escapeHtml(ticket.effort || 'S')}</span></a>`).join('')}</div>` : `<p style="margin:var(--sp-2) 0 0;color:var(--muted);font-size:var(--fs-2);">${t('overview.quick_wins_empty', {}, 'No small-effort actions are currently identified. Review the full action plan for pending work.')}</p>`}
        </details>

        <div class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <h3 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('engines.evidence_readiness_title', {}, 'Evidence readiness')}</h3>
            <span class="tag ${quality.implementation_ready ? 'pill-good' : 'tag-dim'}">${quality.implementation_ready ? t('overview.implementation_ready', {}, 'Implementation ready') : t('overview.implementation_backlog', {}, 'Implementation backlog')}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-3);">
            ${[
              [t('overview.readiness_audit', {}, 'Audit'), readiness.audit?.label || t('overview.not_measured', {}, 'Not measured')],
              [t('overview.readiness_measurement', {}, 'Measurement baseline'), translateBackendLabel(readiness.measurement?.label || quality.measurement_quality?.confidence?.label || t('overview.no_baseline', {}, 'No baseline'))],
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
                    const title = ticketField(ticket, 'title', 'title_en', ticket.name || ticket.id);
                    return `
                  <a class="ticket-item" href="#/plan" style="text-decoration:none;">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                      <div style="display:flex;align-items:center;gap:6px;min-width:0;">
                        <span class="linear-priority ${escapeHtml(String(ticket.priority || 'P1').toLowerCase())}">${escapeHtml(ticket.priority || 'P1')}</span>
                        <span class="ticket-item-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(title)}</span>
                      </div>
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
                      <td><span style="font-family:var(--font-mono);font-weight:600;">${escapeHtml(j.action)}</span></td>
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
    if (sampleBtn && !sampleBtn.disabled) {
      sampleBtn.addEventListener('click', async () => {
        sampleBtn.disabled = true;
        try {
          const res = await projects.triggerSampleGaps(projectId);
          if (res?.status === 'no_gaps') {
            toast.info(t('overview.sample_no_gaps', {}, 'No sample gaps to fill.'));
            return;
          }
          toast.success(t('overview.sample_triggered', {}, 'Sample gap fill queued!'));
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
    if (verifyBtn && !verifyBtn.disabled) {
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
    if (baselineBtn && !baselineBtn.disabled) {
      baselineBtn.addEventListener('click', async () => {
        baselineBtn.disabled = true;
        try {
          await projects.captureVisibilityBaseline(projectId);
          toast.success(t('overview.baseline_captured', {}, 'Visibility baseline captured'));
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
