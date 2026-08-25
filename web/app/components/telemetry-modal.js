/**
 * Live Pipeline Execution & Real-Time Telemetry Monitor
 */

import { projects } from '../api.js?v=3.4';
import { setSafeHtml } from '../safe-html.js';
import { t, translateText } from '../i18n.js';
import { toast } from './toast.js';

let activeStreamTimer = null;
let currentJobId = null;
let currentProjectId = null;
let currentStages = [];
let currentStageIndex = 0;
let highestProgress = 5;
let logOffset = 0;
let autoScroll = true;
let startTime = null;
let elapsedTimer = null;
let streamToken = 0;
let isFetching = false;
let completionHandled = false;
let currentOnClose = null;
let currentOnComplete = null;
let previouslyFocused = null;
let modalKeydownHandler = null;

const AUTOPILOT_STAGES = [
  { key: 'crawl', labelKey: 'telemetry.stage.crawl_website', label: 'Crawl Website' },
  { key: 'audit', labelKey: 'telemetry.stage.site_audit', label: 'Site Audit' },
  { key: 'baseline', labelKey: 'telemetry.stage.brand_questions', label: 'Brand, Competitors & Questions' },
  { key: 'sampling', labelKey: 'telemetry.stage.ai_sampling', label: 'AI Sampling' },
  { key: 'tickets', labelKey: 'telemetry.stage.action_blueprint', label: 'Action Tickets & Blueprint' },
  { key: 'assets', labelKey: 'telemetry.stage.assets_report', label: 'Assets & Diagnostic Report' },
  { key: 'deliverables', labelKey: 'telemetry.stage.core_deliverables', label: 'Core Deliverables' },
  { key: 'verification', labelKey: 'telemetry.stage.verification_pack', label: 'Verification & Delivery Pack' },
];

const STAGE_MAP = {
  autopilot: AUTOPILOT_STAGES,
  bootstrap: AUTOPILOT_STAGES,
  sample: [
    { key: 'init', labelKey: 'telemetry.stage.key_environment', label: 'Key & Environment Setup' },
    { key: 'questions', labelKey: 'telemetry.stage.question_routing', label: 'Question Routing' },
    { key: 'sampling', labelKey: 'telemetry.stage.model_sampling', label: 'Model Sampling' },
    { key: 'finalizing', labelKey: 'telemetry.stage.metrics_archive', label: 'Metrics Archive' },
  ],
  verify: [
    { key: 'init', labelKey: 'telemetry.stage.environment_setup', label: 'Environment Setup' },
    { key: 'crawl', labelKey: 'telemetry.stage.site_crawl', label: 'Site Crawl' },
    { key: 'audit', labelKey: 'telemetry.stage.acceptance_check', label: 'Acceptance Check' },
    { key: 'finalizing', labelKey: 'telemetry.stage.report_generation', label: 'Report Generation' },
  ],
  default: [
    { key: 'init', labelKey: 'telemetry.stage.initialization', label: 'Initialization' },
    { key: 'crawl', labelKey: 'telemetry.stage.data_collection', label: 'Data Collection' },
    { key: 'processing', labelKey: 'telemetry.stage.processing', label: 'Processing' },
    { key: 'finalizing', labelKey: 'telemetry.stage.finalizing_results', label: 'Finalizing Results' },
  ],
};

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s < 10 ? '0' : ''}${s}s` : `${s}s`;
}

function translateLogLine(text) {
  return translateText(String(text || ''));
}

function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function parseLogLine(raw) {
  const line = translateLogLine(String(raw || '').trim());
  if (!line) return '';
  const comparable = line.toLowerCase();
  let colorClass = 'term-normal';
  if (comparable.includes('done') || comparable.includes('100%') || comparable.includes('success') || comparable.includes('complete')) {
    colorClass = 'term-success';
  } else if (comparable.includes('failed') || comparable.includes('error') || comparable.includes('die')) {
    colorClass = 'term-error';
  } else if (comparable.includes('warning') || comparable.includes('skip')) {
    colorClass = 'term-warn';
  } else if (line.includes('===') || line.includes('═══') || comparable.includes('started') || comparable.includes('progress')) {
    colorClass = 'term-accent';
  } else if (line.includes('[geo]') || line.includes('[citeaura]')) {
    colorClass = 'term-brand';
  }
  return `<div class="term-log-row ${colorClass}">${escapeHtml(line)}</div>`;
}

function latestMeaningfulActivity(lines) {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = translateLogLine(String(lines[index] || '').trim());
    if (!line || /^progress\s+/i.test(line)) continue;
    return line.replace(/^[═=\s]+|[═=\s]+$/g, '').trim();
  }
  return '';
}

function stageIndexFromLog(log) {
  let matchedIndex = null;
  const stagePattern = /═══\s*(\d+)\s*\/\s*(\d+)/g;
  for (const match of String(log || '').matchAll(stagePattern)) {
    const current = Number(match[1]);
    const total = Number(match[2]);
    if (total === currentStages.length) {
      matchedIndex = Math.max(0, Math.min(currentStages.length - 1, current - 1));
    }
  }
  return matchedIndex;
}

function stageIndexFromState(stage, progress) {
  const normalized = String(stage || '').toLowerCase();
  if (normalized === 'autopilot' || normalized === 'bootstrap' || normalized === 'preparing') return 0;
  const matchedIndex = currentStages.findIndex((item) => normalized.includes(item.key));
  if (matchedIndex >= 0) return matchedIndex;
  const boundedProgress = Math.max(0, Math.min(99, Number(progress) || 0));
  return Math.min(currentStages.length - 1, Math.floor((boundedProgress / 100) * currentStages.length));
}

function stopTimers() {
  if (activeStreamTimer) {
    clearInterval(activeStreamTimer);
    activeStreamTimer = null;
  }
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

function startElapsedTimer() {
  if (elapsedTimer) clearInterval(elapsedTimer);
  elapsedTimer = setInterval(() => {
    const timer = document.getElementById('tel-timer-badge');
    if (timer && startTime) {
      timer.textContent = t('telemetry.elapsed', { seconds: formatElapsed(Math.floor((Date.now() - startTime) / 1000)) }, 'Elapsed {seconds}s');
    }
  }, 1000);
}

function closeWithCallback() {
  const callback = currentOnClose;
  closeTelemetryModal();
  if (typeof callback === 'function') callback();
}

function bindBackgroundButton() {
  document.getElementById('tel-close-bottom-btn')?.addEventListener('click', closeWithCallback);
}

function renderBackgroundAction() {
  const actionsContainer = document.getElementById('tel-actions-container');
  if (!actionsContainer) return;
  setSafeHtml(actionsContainer, `<button type="button" class="btn btn-secondary btn-sm" id="tel-close-bottom-btn">${t('telemetry.run_bg', {}, 'Run in Background')}</button>`);
  bindBackgroundButton();
}

function updateStepperUI(stageIndex, progress, status) {
  const steps = document.querySelectorAll('.tel-step-item');
  if (!steps.length) return;
  const boundedProgress = Math.max(0, Math.min(100, Number(progress) || 0));
  const fallbackIndex = Math.min(steps.length - 1, Math.floor((boundedProgress / 100) * steps.length));
  const activeIndex = Number.isInteger(stageIndex) ? Math.min(steps.length - 1, stageIndex) : fallbackIndex;

  steps.forEach((step, index) => {
    step.classList.remove('is-active', 'is-done', 'is-failed');
    if (status === 'failed') {
      if (index === activeIndex) step.classList.add('is-failed');
      else if (index < activeIndex) step.classList.add('is-done');
    } else if (status === 'done' || index < activeIndex) {
      step.classList.add('is-done');
    } else if (index === activeIndex) {
      step.classList.add('is-active');
    }
  });
}

function resetForRetry(jobId) {
  currentJobId = jobId;
  logOffset = 0;
  currentStageIndex = 0;
  highestProgress = 5;
  completionHandled = false;
  startTime = Date.now();
  streamToken += 1;
  isFetching = false;

  const jobLabel = document.getElementById('tel-job-id');
  const progressBar = document.getElementById('tel-progress-bar');
  const subtitle = document.getElementById('tel-header-subtitle');
  const statusText = document.getElementById('tel-status-text');
  const activity = document.getElementById('tel-current-activity');
  const term = document.getElementById('tel-terminal');
  const liveDot = document.querySelector('.telemetry-live-dot');
  if (jobLabel) jobLabel.textContent = `Job #${jobId}`;
  if (progressBar) progressBar.style.width = '5%';
  if (subtitle) subtitle.textContent = t('telemetry.retry_waiting', {}, 'Retry queued. Waiting for a worker...');
  if (statusText) statusText.textContent = t('telemetry.retry_running', {}, 'Retry running in Celery worker queue');
  if (activity) activity.textContent = t('telemetry.retry_worker_waiting', {}, 'Waiting for the retry worker to start');
  if (liveDot) liveDot.classList.remove('is-done', 'is-failed');
  if (term) {
    const divider = document.createElement('div');
    divider.className = 'term-log-row term-brand';
    divider.textContent = `--- Retrying as Job #${jobId} ---`;
    term.appendChild(divider);
    term.scrollTop = term.scrollHeight;
  }
  updateStepperUI(currentStageIndex, highestProgress, 'queued');
  renderBackgroundAction();
  startElapsedTimer();
  startLogStream();
}

async function retryCurrentJob() {
  const button = document.getElementById('tel-retry-btn');
  if (button) {
    button.disabled = true;
    button.textContent = t('telemetry.queue_retry', {}, 'Queueing retry...');
  }
  try {
    const retry = await projects.retryJob(currentProjectId, currentJobId);
    const nextJobId = retry?.job_id || retry?.job?.id;
    if (!nextJobId) throw new Error('Retry response did not include a job ID');
    toast.success(t('telemetry.retry_queued', {}, 'Job retry queued'));
    resetForRetry(nextJobId);
  } catch (error) {
    toast.error(error.detail || error.message || t('telemetry.retry_failed', {}, 'Failed to retry job'));
    if (button) {
      button.disabled = false;
      button.textContent = t('telemetry.retry', {}, 'Retry Job');
    }
  }
}

export function openTelemetryModal({
  projectId,
  jobId,
  actionName = 'Pipeline Execution',
  onClose = null,
  onComplete = null,
}) {
  closeTelemetryModal();
  isFetching = false;
  previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  currentProjectId = projectId;
  currentJobId = jobId;
  currentStages = (STAGE_MAP[String(actionName).toLowerCase()] || STAGE_MAP.default).map((stage) => ({
    ...stage,
    label: t(stage.labelKey, {}, stage.label),
  }));
  currentStageIndex = 0;
  highestProgress = 5;
  logOffset = 0;
  autoScroll = true;
  startTime = Date.now();
  completionHandled = false;
  currentOnClose = onClose;
  currentOnComplete = onComplete;
  streamToken += 1;

  let root = document.getElementById('telemetry-modal-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'telemetry-modal-root';
    document.body.appendChild(root);
  }

  const modalHtml = `
    <div class="telemetry-backdrop" id="telemetry-backdrop">
      <div class="telemetry-box" role="dialog" aria-modal="true" aria-labelledby="tel-title">
        <div class="telemetry-header">
          <div class="telemetry-title-cluster">
            <div class="telemetry-live-dot" aria-hidden="true"></div>
            <div class="telemetry-title-copy">
              <div class="telemetry-title" id="tel-title">
                <strong>${escapeHtml(String(actionName).toUpperCase())}</strong>
                <span aria-hidden="true">·</span>
                <span id="tel-job-id">Job #${escapeHtml(jobId)}</span>
              </div>
              <div class="telemetry-subtitle" id="tel-header-subtitle">${t('telemetry.connecting', {}, 'Connecting to the live worker...')}</div>
            </div>
          </div>
          <div class="telemetry-controls">
            <span class="telemetry-timer" id="tel-timer-badge">${t('telemetry.elapsed', { seconds: '0' }, 'Elapsed {seconds}s')}</span>
            <button type="button" class="btn btn-ghost btn-sm" id="tel-autoscroll-btn" title="${t('telemetry.toggle_scroll', {}, 'Toggle automatic log scrolling')}">
              <span id="tel-autoscroll-text">${t('telemetry.auto_scroll_on', {}, 'Auto-scroll: On')}</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" id="tel-copy-btn" title="${t('telemetry.copy_log', {}, 'Copy full log')}">${t('telemetry.copy_log', {}, 'Copy log')}</button>
            <button type="button" class="telemetry-close-btn" id="tel-close-btn" title="${t('telemetry.run_bg', {}, 'Run in background')}" aria-label="${t('telemetry.run_bg', {}, 'Run in background')}">
              <img src="/site-assets/icons/x.svg" width="18" height="18" alt="">
            </button>
          </div>
        </div>

        <div class="telemetry-stepper${currentStages.length > 4 ? ' is-dense' : ''}" id="tel-stepper" style="--telemetry-stage-count:${Math.min(currentStages.length, 4)}">
          ${currentStages.map((stage, index) => `
            <div class="tel-step-item${index === 0 ? ' is-active' : ''}" data-step-index="${index}" title="${escapeHtml(stage.label)}">
              <div class="tel-step-bubble">${index + 1}</div>
              <span class="tel-step-label">${escapeHtml(stage.label)}</span>
            </div>
          `).join('')}
        </div>

        <div class="telemetry-progress-track" role="progressbar" aria-label="${t('telemetry.pipeline_progress', {}, 'Pipeline progress')}" aria-valuemin="0" aria-valuemax="100">
          <div class="telemetry-progress-bar" id="tel-progress-bar" style="width:5%"></div>
        </div>

        <div class="telemetry-activity" aria-live="polite">
          <span class="telemetry-activity-label">${t('telemetry.current_activity', {}, 'Current activity')}</span>
          <span class="telemetry-activity-text" id="tel-current-activity">${t('telemetry.waiting_worker', {}, 'Waiting for the first worker update')}</span>
        </div>

        <div class="telemetry-terminal" id="tel-terminal" role="log" aria-live="polite" aria-label="${t('telemetry.live_pipeline_log', {}, 'Live pipeline log')}">
          <div class="term-log-row term-brand">${escapeHtml(t('telemetry.connecting_engine_log', {}, 'Connecting to CiteAura GEO Engine log stream...'))}</div>
        </div>

        <div class="telemetry-footer">
          <div class="tel-status-info" id="tel-status-info">
            <span class="pulse-dot" aria-hidden="true"></span>
            <span id="tel-status-text">Task running in Celery worker queue</span>
          </div>
          <div class="tel-actions" id="tel-actions-container">
            <button type="button" class="btn btn-secondary btn-sm" id="tel-close-bottom-btn">${t('telemetry.run_bg', {}, 'Run in Background')}</button>
          </div>
        </div>
      </div>
    </div>
  `;

  setSafeHtml(root, modalHtml);

  const dialog = root.querySelector('.telemetry-box');
  modalKeydownHandler = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeWithCallback();
      return;
    }
    if (event.key !== 'Tab' || !dialog) return;
    const focusable = dialog.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  document.addEventListener('keydown', modalKeydownHandler);
  queueMicrotask(() => dialog?.querySelector('button, [href], input, select, textarea')?.focus?.({ preventScroll: true }));

  document.getElementById('tel-close-btn')?.addEventListener('click', closeWithCallback);
  bindBackgroundButton();
  document.getElementById('telemetry-backdrop')?.addEventListener('click', (event) => {
    if (event.target.id === 'telemetry-backdrop') closeWithCallback();
  });

  const scrollButton = document.getElementById('tel-autoscroll-btn');
  const scrollText = document.getElementById('tel-autoscroll-text');
  scrollButton?.addEventListener('click', () => {
    autoScroll = !autoScroll;
    if (scrollText) scrollText.textContent = autoScroll
      ? t('telemetry.auto_scroll_on', {}, 'Auto-scroll: On')
      : t('telemetry.auto_scroll_off', {}, 'Auto-scroll: Off');
    scrollButton.classList.toggle('is-dim', !autoScroll);
  });

  document.getElementById('tel-copy-btn')?.addEventListener('click', () => {
    const terminal = document.getElementById('tel-terminal');
    if (terminal && navigator.clipboard) {
      navigator.clipboard.writeText(terminal.innerText).then(() => toast.success(t('telemetry.copied', {}, 'Log copied to clipboard')));
    }
  });

  startElapsedTimer();
  startLogStream();
}

async function fetchLogChunk(token) {
  if (!currentProjectId || !currentJobId || token !== streamToken || isFetching) return;
  isFetching = true;
  const requestedProjectId = currentProjectId;
  const requestedJobId = currentJobId;
  try {
    const job = await projects.getJob(requestedProjectId, requestedJobId, logOffset);
    if (!job || token !== streamToken || requestedJobId !== currentJobId) return;

    const terminal = document.getElementById('tel-terminal');
    const progressBar = document.getElementById('tel-progress-bar');
    const progressTrack = progressBar?.parentElement;
    const statusText = document.getElementById('tel-status-text');
    const subtitle = document.getElementById('tel-header-subtitle');
    const activity = document.getElementById('tel-current-activity');
    const actionsContainer = document.getElementById('tel-actions-container');
    const liveDot = document.querySelector('.telemetry-live-dot');

    if (job.log) {
      const lines = job.log.split('\n').filter(Boolean);
      if (terminal) {
        lines.forEach((line) => {
          const wrapper = document.createElement('div');
          setSafeHtml(wrapper, parseLogLine(line));
          terminal.appendChild(wrapper.firstElementChild || wrapper);
        });
        if (autoScroll) terminal.scrollTop = terminal.scrollHeight;
      }
      const nextStageIndex = stageIndexFromLog(job.log);
      if (Number.isInteger(nextStageIndex)) {
        currentStageIndex = Math.max(currentStageIndex, nextStageIndex);
        highestProgress = Math.max(highestProgress, Math.round(((nextStageIndex + 1) / currentStages.length) * 90));
      }
      const nextActivity = latestMeaningfulActivity(lines);
      if (activity && nextActivity) activity.textContent = nextActivity;
    }

    if (typeof job.log_offset === 'number') logOffset = job.log_offset;
    const reportedProgress = job.progress || (job.status === 'done' ? 100 : (job.status === 'running' ? 10 : 5));
    highestProgress = job.status === 'done' ? 100 : Math.max(highestProgress, Math.min(99, reportedProgress));
    if (!job.log || !Number.isInteger(stageIndexFromLog(job.log))) {
      currentStageIndex = Math.max(currentStageIndex, stageIndexFromState(job.stage, highestProgress));
    }
    if (progressBar) progressBar.style.width = `${highestProgress}%`;
    if (progressTrack) progressTrack.setAttribute('aria-valuenow', String(highestProgress));

    if (subtitle) {
      const stageLabel = currentStages[currentStageIndex]?.label || job.stage || t('telemetry.executing', {}, 'Executing');
      subtitle.textContent = `${stageLabel} · ${highestProgress}% · ${job.status}`;
    }
    updateStepperUI(currentStageIndex, highestProgress, job.status);

    if (job.status === 'done') {
      stopTimers();
      liveDot?.classList.add('is-done');
      if (statusText) statusText.textContent = `${t('telemetry.completed_in', {}, 'Task completed in {seconds}s').replace('{seconds}', formatElapsed(Math.floor((Date.now() - startTime) / 1000)))}`;
      if (activity) activity.textContent = t('telemetry.results_ready', {}, 'Pipeline complete. Results are ready to review.');
      if (actionsContainer) {
        setSafeHtml(actionsContainer, `<button type="button" class="btn btn-primary btn-sm" id="tel-view-result-btn">${t('telemetry.view_results', {}, 'View Results')}</button>`);
        document.getElementById('tel-view-result-btn')?.addEventListener('click', () => {
          closeTelemetryModal();
          if (location.hash !== '#/overview') location.hash = '#/overview';
        });
      }
      if (!completionHandled) {
        completionHandled = true;
        const callback = currentOnComplete;
        if (typeof callback === 'function') {
          Promise.resolve(callback(job)).catch((error) => console.warn('Telemetry completion refresh failed:', error));
        }
      }
    } else if (job.status === 'failed') {
      stopTimers();
      liveDot?.classList.add('is-failed');
      const errorMessage = job.error || t('telemetry.check_log', {}, 'Check the log for details');
      if (statusText) statusText.textContent = `${t('telemetry.task_failed', {}, 'Task failed')}: ${errorMessage}`;
      if (subtitle) subtitle.textContent = `${currentStages[currentStageIndex]?.label || t('telemetry.pipeline', {}, 'Pipeline')} · ${t('telemetry.failed', {}, 'failed')}`;
      if (activity) activity.textContent = errorMessage;
      if (terminal && job.error && !job.log?.includes(job.error)) {
        const row = document.createElement('div');
        row.className = 'term-log-row term-error';
        row.textContent = `${t('telemetry.error_prefix', {}, 'Error')}: ${job.error}`;
        terminal.appendChild(row);
        terminal.scrollTop = terminal.scrollHeight;
      }
      if (actionsContainer) {
        const retryAction = job.can_retry
          ? `<button type="button" class="btn btn-danger btn-sm" id="tel-retry-btn">${t('telemetry.retry', {}, 'Retry Job')}</button>`
          : `<button type="button" class="btn btn-secondary btn-sm" id="tel-close-bottom-btn">${t('common.close', {}, 'Close')}</button>`;
        setSafeHtml(actionsContainer, retryAction);
        if (job.can_retry) document.getElementById('tel-retry-btn')?.addEventListener('click', retryCurrentJob);
        else bindBackgroundButton();
      }
    }
  } catch (error) {
    if (token === streamToken) {
      const subtitle = document.getElementById('tel-header-subtitle');
      if (subtitle) subtitle.textContent = t('telemetry.live_updates_unavailable', {}, 'Live updates temporarily unavailable. Retrying...');
    }
    console.warn('Telemetry log fetch error:', error);
  } finally {
    isFetching = false;
  }
}

function startLogStream() {
  if (activeStreamTimer) clearInterval(activeStreamTimer);
  const token = streamToken;
  fetchLogChunk(token);
  activeStreamTimer = setInterval(() => fetchLogChunk(token), 1200);
}

export function closeTelemetryModal() {
  stopTimers();
  streamToken += 1;
  currentJobId = null;
  currentProjectId = null;
  currentStages = [];
  currentOnClose = null;
  currentOnComplete = null;
  isFetching = false;
  if (modalKeydownHandler) {
    document.removeEventListener('keydown', modalKeydownHandler);
    modalKeydownHandler = null;
  }
  const root = document.getElementById('telemetry-modal-root');
  if (root) root.replaceChildren();
  const focusTarget = previouslyFocused;
  previouslyFocused = null;
  if (focusTarget && document.contains(focusTarget)) focusTarget.focus({ preventScroll: true });
}
