import { escapeHtml, setSafeHtml } from '../safe-html.js';
import { tError } from '../i18n.js';
import { confirmModal } from './modal.js';

const JOB_ACTION_LABELS = {
  crawl: ['telemetry.stage.crawl_website', 'Crawl Website'],
  audit: ['telemetry.stage.site_audit', 'Site Audit'],
  sample: ['telemetry.stage.ai_sampling', 'AI Sampling'],
  bootstrap: ['telemetry.stage.brand_questions', 'Auto-bootstrap Baseline'],
  autopilot: ['telemetry.stage.brand_questions', 'Autopilot Bootstrap'],
  serve: ['telemetry.stage.core_deliverables', 'Run Full Optimization Cycle'],
  verify: ['telemetry.stage.verification_pack', 'Closed-Loop Verify'],
  deliver: ['telemetry.stage.verification_pack', 'Compile Delivery Pack'],
};

const JOB_STAGE_LABELS = {
  queued: ['telemetry.queued', 'Queued'],
  running: ['telemetry.executing', 'Executing'],
  executing: ['telemetry.executing', 'Executing'],
  evidence: ['telemetry.stage.evidence_verification', 'Evidence Verification'],
  gapfill: ['telemetry.stage.evidence_gap_fill', 'Evidence Gap-Fill'],
  compile: ['telemetry.stage.compile_artifacts', 'Compile Deliverables'],
  package: ['telemetry.stage.packaging_archive', 'Packaging & Archive'],
  crawl: ['telemetry.stage.crawl_website', 'Crawl Website'],
  audit: ['telemetry.stage.site_audit', 'Site Audit'],
  sampling: ['telemetry.stage.ai_sampling', 'AI Sampling'],
  finalizing: ['telemetry.stage.finalizing_results', 'Finalizing Results'],
  complete: ['telemetry.results_ready', 'Results ready'],
  failed: ['telemetry.failed', 'failed'],
  canceled: ['job.canceled', 'Canceled'],
};

export function createJobMonitor({ state, projects, toast, t, openTelemetryModal, renderApp }) {
  let lastJobStatus = null;
  let lastJobId = null;
  let pollingTimer = null;

  function jobActionLabel(action) {
    const normalized = String(action || '').toLowerCase();
    const [key, fallback] = JOB_ACTION_LABELS[normalized] || [];
    return key ? t(key, {}, fallback) : (action || t('common.job', {}, 'Job'));
  }

  function jobStageLabel(stage, status) {
    const normalized = String(stage || status || '').toLowerCase();
    const [key, fallback] = JOB_STAGE_LABELS[normalized] || [];
    return key ? t(key, {}, fallback) : (stage || t('common.job', {}, 'Job'));
  }

  async function requestCancel(job) {
    if (!job?.id || !state.activeProjectId) return;
    const confirmed = await confirmModal(
      t('job.cancel_confirm_body', {}, 'The task stops within a couple of seconds. Work already written to disk stays.'),
      {
        title: t('job.cancel_confirm_title', {}, 'Cancel this task?'),
        confirmText: t('job.cancel_btn', {}, 'Cancel task'),
        isDanger: true,
      },
    );
    if (!confirmed) return;
    try {
      await projects.cancelJob(state.activeProjectId, job.id);
      toast.info(t('job.cancel_requested', {}, 'Stopping…'));
      checkJobs();
    } catch (err) {
      toast.error(tError(err));
    }
  }

  async function checkJobs() {
    if (!state.activeProjectId || !state.user) return;
    const requestedProjectId = state.activeProjectId;
    try {
      const jobs = await projects.getJobs(requestedProjectId, { limit: 20 });
      // 切换项目后旧请求晚到：不能把旧项目的任务写进新项目的顶栏。
      if (requestedProjectId !== state.activeProjectId) return;
      const active = Array.isArray(jobs) ? jobs.find((j) => j.status === 'running' || j.status === 'queued') : null;
      const indicator = document.getElementById('active-job-indicator');
      if (active) {
        state.activeJob = active;
        ensurePolling();
        if (indicator) {
          indicator.style.display = 'inline-flex';
          const actionLabel = jobActionLabel(active.action);
          const stageLabel = active.cancel_requested
            ? t('job.cancel_requested', {}, 'Stopping…')
            : jobStageLabel(active.stage, active.status);
          const progressVal = Number.isFinite(Number(active.progress))
            ? Number(active.progress)
            : (active.status === 'running' ? 45 : 10);
          const cancelLabel = escapeHtml(t('job.cancel_btn', {}, 'Cancel task'));
          const stopDisabled = active.cancel_requested || active.can_cancel === false;
          setSafeHtml(indicator, `
            <div class="active-job-capsule-wrap">
              <button type="button" class="active-job-capsule" id="header-job-capsule" title="${t('telemetry.title', {}, 'Click to view live execution logs & telemetry')}" aria-label="${escapeHtml(`${actionLabel}: ${stageLabel}`)}">
                <div class="job-capsule-content">
                  <span class="job-spinner"></span>
                  <span class="job-action-label">${escapeHtml(actionLabel)}</span>
                  <span class="job-stage-badge">${escapeHtml(stageLabel)}</span>
                  <span class="job-pct-badge">${progressVal}%</span>
                </div>
                <div class="job-capsule-bar"><div class="job-capsule-fill" style="width: ${progressVal}%;"></div></div>
              </button>
              <button type="button" class="job-stop-btn" id="header-job-stop" title="${cancelLabel}" aria-label="${cancelLabel}" ${stopDisabled ? 'disabled' : ''}>
                <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              </button>
            </div>
          `);
          document.getElementById('header-job-capsule')?.addEventListener('click', () => {
            openTelemetryModal({ projectId: state.activeProjectId, jobId: active.id, actionName: active.action });
          });
          document.getElementById('header-job-stop')?.addEventListener('click', () => requestCancel(active));
        }
        lastJobStatus = active.status;
        lastJobId = active.id;
      } else {
        if (state.activeJob && (lastJobStatus === 'running' || lastJobStatus === 'queued')) {
          const finished = jobs.find((job) => job.id === lastJobId);
          if (finished?.status === 'done') toast.success(t('pipeline.task_completed', {}, 'Pipeline task completed successfully!'));
          else if (finished?.status === 'failed') toast.error(finished.error || t('pipeline.task_failed', {}, 'Pipeline task failed'));
          else if (finished?.status === 'canceled') toast.info(t('job.canceled', {}, 'Task canceled'));
          const keepEditors = new Set(['facts', 'assets', 'branding', 'project-settings', 'outreach', 'publishing', 'questions']);
          if (!keepEditors.has(state.currentRoute)) renderApp();
        }
        state.activeJob = null;
        lastJobStatus = null;
        lastJobId = null;
        if (indicator) indicator.style.display = 'none';
      }
    } catch (error) {
      const indicator = document.getElementById('active-job-indicator');
      if (indicator && state.activeJob) indicator.setAttribute('aria-label', t('common.unavailable', {}, 'Task status temporarily unavailable'));
      console.warn('Job status refresh failed:', error);
    }
  }

  function pollTick() {
    // Never hammer protected endpoints from a hidden tab.
    if (document.hidden) return;
    if (!state.activeJob) {
      stopJobPolling();
      return;
    }
    checkJobs();
  }

  function ensurePolling() {
    if (pollingTimer !== null) return;
    state.isJobPolling = true;
    pollingTimer = window.setInterval(pollTick, 2500);
  }

  function startJobPolling() {
    if (pollingTimer !== null) return;
    // Arm the interval first, then take one immediate probe so a job started
    // elsewhere still shows up. The interval stops itself on the first tick
    // when there is no active job, and re-arms when one is discovered.
    ensurePolling();
    checkJobs();
  }

  function stopJobPolling() {
    if (pollingTimer !== null) {
      window.clearInterval(pollingTimer);
      pollingTimer = null;
    }
    state.isJobPolling = false;
    state.activeJob = null;
    lastJobStatus = null;
    lastJobId = null;
  }

  return { checkJobs, startJobPolling, stopJobPolling, jobActionLabel, jobStageLabel };
}
