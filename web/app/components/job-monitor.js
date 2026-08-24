import { escapeHtml, setSafeHtml } from '../safe-html.js';

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
  crawl: ['telemetry.stage.crawl_website', 'Crawl Website'],
  audit: ['telemetry.stage.site_audit', 'Site Audit'],
  sampling: ['telemetry.stage.ai_sampling', 'AI Sampling'],
  finalizing: ['telemetry.stage.finalizing_results', 'Finalizing Results'],
  complete: ['telemetry.results_ready', 'Results ready'],
  failed: ['telemetry.failed', 'failed'],
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

  async function checkJobs() {
    if (!state.activeProjectId || !state.user) return;
    try {
      const jobs = await projects.getJobs(state.activeProjectId, { limit: 20 });
      const active = Array.isArray(jobs) ? jobs.find((j) => j.status === 'running' || j.status === 'queued') : null;
      const indicator = document.getElementById('active-job-indicator');
      if (active) {
        state.activeJob = active;
        if (indicator) {
          indicator.style.display = 'inline-flex';
          const actionLabel = jobActionLabel(active.action);
          const stageLabel = jobStageLabel(active.stage, active.status);
          const progressVal = Number.isFinite(Number(active.progress))
            ? Number(active.progress)
            : (active.status === 'running' ? 45 : 10);
          setSafeHtml(indicator, `
            <div class="active-job-capsule" id="header-job-capsule" title="${t('telemetry.title', {}, 'Click to view live execution logs & telemetry')}">
              <div class="job-capsule-content">
                <span class="job-spinner"></span>
                <span class="job-action-label">${escapeHtml(actionLabel)}</span>
                <span class="job-stage-badge">${escapeHtml(stageLabel)}</span>
                <span class="job-pct-badge">${progressVal}%</span>
              </div>
              <div class="job-capsule-bar"><div class="job-capsule-fill" style="width: ${progressVal}%;"></div></div>
            </div>
          `);
          document.getElementById('header-job-capsule')?.addEventListener('click', () => {
            openTelemetryModal({ projectId: state.activeProjectId, jobId: active.id, actionName: active.action });
          });
        }
        lastJobStatus = active.status;
        lastJobId = active.id;
      } else {
        if (state.activeJob && (lastJobStatus === 'running' || lastJobStatus === 'queued')) {
          const finished = jobs.find((job) => job.id === lastJobId);
          if (finished?.status === 'done') toast.success(t('pipeline.task_completed', {}, 'Pipeline task completed successfully!'));
          else if (finished?.status === 'failed') toast.error(finished.error || t('pipeline.task_failed', {}, 'Pipeline task failed'));
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

  function startJobPolling() {
    if (pollingTimer !== null) return;
    state.isJobPolling = true;
    pollingTimer = window.setInterval(checkJobs, 2500);
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
