/**
 * Live Pipeline Execution & Real-Time Telemetry Monitor
 */

import { projects } from '../api.js';
import { t } from '../i18n.js';
import { setSafeHtml } from '../safe-html.js';
import { toast } from './toast.js';

let activeStreamTimer = null;
let currentJobId = null;
let currentProjectId = null;
let logOffset = 0;
let autoScroll = true;
let startTime = null;
let elapsedTimer = null;

const STAGE_MAP = {
  sample: [
    { key: 'init', label: '1. BYOK Key & Environment Setup' },
    { key: 'crawling', label: '2. Target Questions & Query Routing' },
    { key: 'sampling', label: '3. Multi-Model Inference & Citations' },
    { key: 'finalizing', label: '4. Visibility Synthesis & Metrics Archive' },
  ],
  verify: [
    { key: 'init', label: '1. Verification Environment Setup' },
    { key: 'crawling', label: '2. Incremental Site Crawl & Extraction' },
    { key: 'auditing', label: '3. Rule Matching & Acceptance Check' },
    { key: 'finalizing', label: '4. Ticket Updates & Report Generation' },
  ],
  bootstrap: [
    { key: 'init', label: '1. Brand Baseline & Configuration' },
    { key: 'crawling', label: '2. Site Technical & Page Structure Crawl' },
    { key: 'auditing', label: '3. GEO Entity Diagnostics & Gap Audit' },
    { key: 'finalizing', label: '4. 13 Standard Action Tickets Synthesis' },
  ],
  default: [
    { key: 'init', label: '1. Environment Initialization' },
    { key: 'crawling', label: '2. Data Crawling & Extraction' },
    { key: 'processing', label: '3. Engine Algorithmic Processing' },
    { key: 'finalizing', label: '4. Deliverables Compilation & Archive' },
  ],
};

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s < 10 ? '0' : ''}${s}s` : `${s}s`;
}

const CLIENT_LOG_TRANSLATIONS = [
  [/跳过（缺 API Key）：(.*)/, 'Skipped (Missing API Key): $1'],
  [/\[(.*?)\] (cn|global|both) 市场 · (\d+) 题 × (\d+) 轮/, '[$1] $2 market · $3 questions × $4 round(s)'],
  [/采样完成：(\d+) 条 → (.*)/, 'Sampling complete: $1 answers collected → $2'],
  [/=== 重抓站点 ===/, '=== Re-crawling Site ==='],
  [/抓取 (.*?)（上限 (\d+) 页）/, 'Crawling $1 (limit: $2 pages)'],
  [/完成：(\d+)\/(\d+) 页可访问 → (.*)/, 'Complete: $1/$2 pages accessible → $3'],
  [/=== 重跑体检 ===/, '=== Re-running Site Audit ==='],
  [/体检完成：(\d+) 页，均分 ([\d\.]+)，分布 (.*?) → (.*)/, 'Audit complete: $1 pages, avg score $2, grade distribution $3 → $4'],
  [/验收：通过 (\d+) \/ 未达标 (\d+) \/ 待人工 (\d+)；状态变更 (\d+) 条/, 'Verification: Passed $1 / Unmet $2 / Manual review $3; Status changed: $4 items'],
  [/推导品牌事实…/, 'Inferring brand facts...'],
  [/设计问题库…/, 'Designing target question bank...'],
  [/推导竞品候选…/, 'Inferring competitor candidates...'],
  [/自动引导：从 (\d+) 字官网正文推导项目底座/, 'Auto-bootstrap: Inferring brand baseline from $1 characters of text'],
  [/生成 (\d+) 项资产 → (.*)/, 'Generated $1 asset(s) → $2'],
  [/三份交付物已生成 → (.*)/, 'Three core deliverables generated → $1'],
  [/交付包已生成 → (.*)/, 'Delivery package compiled → $1'],
  [/错误：抓取失败：没有页面返回 200，检查站点可达性\/WAF/, 'Error: Crawl failed: No page returned 200 OK. Check site accessibility or WAF.'],
  [/某平台采样中断：(.*)/, 'Engine query interrupted: $1'],
  [/═══ 1\/8 抓取官网 ═══/, '═══ 1/8 Crawl Website ═══'],
  [/═══ 2\/8 体检 ═══/, '═══ 2/8 Site Audit ═══'],
  [/═══ 3\/8 自动推导品牌事实、竞品与问题库 ═══/, '═══ 3/8 Bootstrap Baseline & Question Bank ═══'],
  [/═══ 3\/8 已有问题库，跳过自动推导 ═══/, '═══ 3/8 Existing questions found, skipping bootstrap ═══'],
  [/═══ 4\/8 AI 答案采样 ═══/, '═══ 4/8 AI Sampling ═══'],
  [/═══ 5\/8 工单与建设蓝图 ═══/, '═══ 5/8 Action Tickets & Blueprint ═══'],
  [/═══ 6\/8 资产与报告 ═══/, '═══ 6/8 Assets & Diagnostic Report ═══'],
  [/═══ 7\/8 三份交付物 ═══/, '═══ 7/8 Three Core Deliverables ═══'],
  [/═══ 8\/8 验收与打包 ═══/, '═══ 8/8 Verification & Delivery Package ═══'],
  [/跳过：--no-sample/, 'Skipped: --no-sample'],
  [/跳过 (.*?)：问题库里没有 (.*?) 市场的问题/, 'Skipped $1: No questions matching $2 market in question library'],
];

function translateLogLine(text) {
  let res = String(text || '');
  CLIENT_LOG_TRANSLATIONS.forEach(([regex, repl]) => {
    res = res.replace(regex, repl);
  });
  return res;
}

function parseLogLine(raw) {
  const line = translateLogLine(String(raw || '').trim());
  if (!line) return '';
  let colorClass = 'term-normal';
  if (line.includes('✓') || line.includes('done') || line.includes('100%') || line.includes('success') || line.includes('complete')) {
    colorClass = 'term-success';
  } else if (line.includes('failed') || line.includes('Error') || line.includes('die')) {
    colorClass = 'term-error';
  } else if (line.includes('warning') || line.includes('skip') || line.includes('Skipped')) {
    colorClass = 'term-warn';
  } else if (line.includes('===') || line.includes('═══') || line.includes('started') || line.includes('progress')) {
    colorClass = 'term-accent';
  } else if (line.includes('[geo]') || line.includes('[citeaura]')) {
    colorClass = 'term-brand';
  }
  return `<div class="term-log-row ${colorClass}">${escapeHtml(line)}</div>`;
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function openTelemetryModal({ projectId, jobId, actionName = 'Pipeline Execution', onClose = null }) {
  closeTelemetryModal();

  currentProjectId = projectId;
  currentJobId = jobId;
  logOffset = 0;
  autoScroll = true;
  startTime = Date.now();

  let root = document.getElementById('telemetry-modal-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'telemetry-modal-root';
    document.body.appendChild(root);
  }

  const stages = STAGE_MAP[actionName] || STAGE_MAP.default;

  const modalHtml = `
    <div class="telemetry-backdrop" id="telemetry-backdrop">
      <div class="telemetry-box">
        <!-- Header -->
        <div class="telemetry-header">
          <div class="telemetry-title-cluster">
            <div class="telemetry-live-dot" aria-hidden="true"></div>
            <div>
              <div class="telemetry-title">
                <strong>${escapeHtml(actionName.toUpperCase())}</strong> · Job #${jobId}
              </div>
              <div class="telemetry-subtitle" id="tel-header-subtitle">
                Connecting to live computing worker...
              </div>
            </div>
          </div>
          <div class="telemetry-controls">
            <span class="telemetry-timer" id="tel-timer-badge">⏱ 0s</span>
            <button type="button" class="btn btn-ghost btn-sm" id="tel-autoscroll-btn" title="Toggle Auto Scroll">
              <span id="tel-autoscroll-text">📜 Auto-scroll: ON</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" id="tel-copy-btn" title="Copy full log">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>Copy</span>
            </button>
            <button type="button" class="telemetry-close-btn" id="tel-close-btn" aria-label="Close">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>

        <!-- 4-Stage Stepper -->
        <div class="telemetry-stepper" id="tel-stepper">
          ${stages.map((st, i) => `
            <div class="tel-step-item" data-step-index="${i}">
              <div class="tel-step-bubble">${i + 1}</div>
              <span class="tel-step-label">${st.label}</span>
            </div>
          `).join('')}
        </div>

        <!-- Progress Track -->
        <div class="telemetry-progress-track">
          <div class="telemetry-progress-bar" id="tel-progress-bar" style="width: 5%;"></div>
        </div>

        <!-- Monospace Terminal -->
        <div class="telemetry-terminal" id="tel-terminal">
          <div class="term-log-row term-brand">▶ Connecting to CiteAura GEO Engine log stream...</div>
        </div>

        <!-- Footer -->
        <div class="telemetry-footer">
          <div class="tel-status-info" id="tel-status-info">
            <span class="pulse-dot"></span>
            <span id="tel-status-text">Task running in Celery worker queue</span>
          </div>
          <div class="tel-actions" id="tel-actions-container">
            <button type="button" class="btn btn-secondary btn-sm" id="tel-close-bottom-btn">Run in Background</button>
          </div>
        </div>
      </div>
    </div>
  `;

  setSafeHtml(root, modalHtml);

  document.getElementById('tel-close-btn')?.addEventListener('click', () => {
    closeTelemetryModal();
    if (typeof onClose === 'function') onClose();
  });
  document.getElementById('tel-close-bottom-btn')?.addEventListener('click', () => {
    closeTelemetryModal();
    if (typeof onClose === 'function') onClose();
  });
  document.getElementById('telemetry-backdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'telemetry-backdrop') {
      closeTelemetryModal();
      if (typeof onClose === 'function') onClose();
    }
  });

  const scrollBtn = document.getElementById('tel-autoscroll-btn');
  const scrollText = document.getElementById('tel-autoscroll-text');
  if (scrollBtn && scrollText) {
    scrollBtn.addEventListener('click', () => {
      autoScroll = !autoScroll;
      scrollText.textContent = `📜 Auto-scroll: ${autoScroll ? 'ON' : 'OFF'}`;
      scrollBtn.classList.toggle('is-dim', !autoScroll);
    });
  }

  const copyBtn = document.getElementById('tel-copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const term = document.getElementById('tel-terminal');
      if (term && navigator.clipboard) {
        navigator.clipboard.writeText(term.innerText).then(() => {
          toast.success('Log copied to clipboard');
        });
      }
    });
  }

  if (elapsedTimer) clearInterval(elapsedTimer);
  elapsedTimer = setInterval(() => {
    const el = document.getElementById('tel-timer-badge');
    if (el && startTime) {
      const sec = Math.floor((Date.now() - startTime) / 1000);
      el.textContent = `⏱ ${formatElapsed(sec)}`;
    }
  }, 1000);

  startLogStream();
}

function updateStepperUI(stage, progress, status) {
  const steps = document.querySelectorAll('.tel-step-item');
  let activeIndex = 0;
  if (progress >= 85 || status === 'done') {
    activeIndex = 3;
  } else if (progress >= 50) {
    activeIndex = 2;
  } else if (progress >= 20) {
    activeIndex = 1;
  }

  steps.forEach((st, idx) => {
    st.classList.remove('is-active', 'is-done', 'is-failed');
    if (status === 'failed') {
      if (idx === activeIndex) st.classList.add('is-failed');
      else if (idx < activeIndex) st.classList.add('is-done');
    } else if (idx < activeIndex || status === 'done') {
      st.classList.add('is-done');
    } else if (idx === activeIndex) {
      st.classList.add('is-active');
    }
  });
}

async function fetchLogChunk() {
  if (!currentProjectId || !currentJobId) return;
  try {
    const job = await projects.getJob(currentProjectId, currentJobId, logOffset);
    if (!job) return;

    const term = document.getElementById('tel-terminal');
    const progressBar = document.getElementById('tel-progress-bar');
    const statusText = document.getElementById('tel-status-text');
    const subtitle = document.getElementById('tel-header-subtitle');
    const actionsContainer = document.getElementById('tel-actions-container');

    if (job.log && term) {
      const lines = job.log.split('\n').filter(Boolean);
      lines.forEach((line) => {
        const div = document.createElement('div');
        div.innerHTML = parseLogLine(line);
        term.appendChild(div.firstElementChild || div);
      });
      if (autoScroll) {
        term.scrollTop = term.scrollHeight;
      }
    }

    if (typeof job.log_offset === 'number') {
      logOffset = job.log_offset;
    }

    const pct = job.progress || (job.status === 'done' ? 100 : (job.status === 'running' ? 45 : 10));
    if (progressBar) progressBar.style.width = `${pct}%`;

    if (subtitle) {
      subtitle.textContent = `Stage: ${job.stage || 'executing'} · Status: ${job.status}`;
    }

    updateStepperUI(job.stage, pct, job.status);

    if (job.status === 'done') {
      if (activeStreamTimer) clearInterval(activeStreamTimer);
      if (statusText) statusText.textContent = `✔ Task completed successfully in ${formatElapsed(Math.floor((Date.now() - startTime) / 1000))}`;
      if (actionsContainer) {
        actionsContainer.innerHTML = `
          <a href="#/overview" class="btn btn-primary btn-sm" id="tel-view-result-btn">
            <span>View Latest Results →</span>
          </a>
        `;
        document.getElementById('tel-view-result-btn')?.addEventListener('click', () => {
          closeTelemetryModal();
        });
      }
    } else if (job.status === 'failed') {
      if (activeStreamTimer) clearInterval(activeStreamTimer);
      if (statusText) statusText.textContent = `✖ Task failed: ${job.error || 'Check log details'}`;
      if (actionsContainer) {
        actionsContainer.innerHTML = `
          <button type="button" class="btn btn-danger btn-sm" id="tel-retry-btn">
            <span>Retry Job ↺</span>
          </button>
        `;
        document.getElementById('tel-retry-btn')?.addEventListener('click', async () => {
          try {
            await projects.retryJob(currentProjectId, currentJobId);
            toast.success('Job retry queued!');
            closeTelemetryModal();
          } catch (e) {
            toast.error(e.detail || 'Failed to retry job');
          }
        });
      }
    }
  } catch (err) {
    console.warn('Telemetry log fetch error:', err);
  }
}

function startLogStream() {
  if (activeStreamTimer) clearInterval(activeStreamTimer);
  fetchLogChunk();
  activeStreamTimer = setInterval(fetchLogChunk, 1200);
}

export function closeTelemetryModal() {
  if (activeStreamTimer) {
    clearInterval(activeStreamTimer);
    activeStreamTimer = null;
  }
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
  currentJobId = null;
  currentProjectId = null;
  const root = document.getElementById('telemetry-modal-root');
  if (root) root.innerHTML = '';
}
