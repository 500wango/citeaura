/**
 * CiteAura 
 */

import { auth, projects, onAuthFailure } from './api.js?v=3.4';
import { t, loadCatalogs, getLocale, setLocale } from './i18n.js';
import { toast } from './components/toast.js';
import { setSafeHtml } from './safe-html.js';
import { openTelemetryModal } from './components/telemetry-modal.js?v=2.6';

/* ----------  ---------- */
export const TRACKS = [
  {
    id: 'overview',
    labelKey: 'nav.track_overview',
    defaultLabel: 'Overview',
    icon: 'layout-dashboard',
    defaultView: 'overview',
    views: [{ id: 'overview', labelKey: 'nav.overview', defaultLabel: 'Brand Overview' }],
  },
  {
    id: 'monitor',
    labelKey: 'nav.track_monitor',
    defaultLabel: 'Monitor',
    icon: 'radar',
    defaultView: 'engines',
    views: [
      { id: 'engines', labelKey: 'nav.engines', defaultLabel: 'AI Visibility Matrix' },
      { id: 'channels', labelKey: 'nav.channels', defaultLabel: 'Citation Sources' },
      { id: 'competitors', labelKey: 'nav.competitors', defaultLabel: 'Competitor Benchmark' },
    ],
  },
  {
    id: 'diagnostics',
    labelKey: 'nav.track_diagnostics',
    defaultLabel: 'Diagnostics',
    icon: 'scan-search',
    defaultView: 'siteaudit',
    views: [
      { id: 'siteaudit', labelKey: 'nav.siteaudit', defaultLabel: 'Site-wide GEO Audit' },
      { id: 'gaps', labelKey: 'nav.gaps', defaultLabel: 'Perception Gaps' },
      { id: 'questions', labelKey: 'nav.questions', defaultLabel: 'Target Questions' },
      { id: 'facts', labelKey: 'nav.facts', defaultLabel: 'Brand Fact Library' },
    ],
  },
  {
    id: 'execution',
    labelKey: 'nav.track_execution',
    defaultLabel: 'Execution',
    icon: 'list-checks',
    defaultView: 'plan',
    views: [
      { id: 'plan', labelKey: 'nav.plan', defaultLabel: 'Action Tickets' },
      { id: 'workbench', labelKey: 'nav.workbench_view', defaultLabel: 'Interactive Workbench' },
      { id: 'assets', labelKey: 'nav.assets', defaultLabel: 'Assets & Templates' },
      { id: 'outreach', labelKey: 'nav.outreach', defaultLabel: 'Media Outreach' },
      { id: 'publishing', labelKey: 'nav.publishing', defaultLabel: 'Publishing Destinations' },
      { id: 'verify', labelKey: 'nav.verify', defaultLabel: 'Closed-Loop Verify' },
    ],
  },
  {
    id: 'delivery',
    labelKey: 'nav.track_delivery',
    defaultLabel: 'Delivery',
    icon: 'package-check',
    defaultView: 'report',
    views: [
      { id: 'report', labelKey: 'nav.report', defaultLabel: 'Client Delivery Packs' },
      { id: 'branding', labelKey: 'nav.branding', defaultLabel: 'White-Label Branding' },
    ],
  },
  {
    id: 'management',
    labelKey: 'nav.track_management',
    defaultLabel: 'Settings',
    icon: 'settings-2',
    defaultView: 'project-settings',
    views: [
      { id: 'project-settings', labelKey: 'nav.project_settings', defaultLabel: 'Brand Settings' },
      { id: 'engine-settings', labelKey: 'nav.engine_settings', defaultLabel: 'Model Keys (BYOK)' },
      { id: 'automation', labelKey: 'nav.automation', defaultLabel: 'Automated Schedule' },
      { id: 'team', labelKey: 'nav.team', defaultLabel: 'Team Members' },
      { id: 'billing', labelKey: 'nav.billing', defaultLabel: 'Billing & Plans' },
      { id: 'security', labelKey: 'nav.security', defaultLabel: 'Enterprise Security' },
      { id: 'archive', labelKey: 'nav.archive', defaultLabel: 'Backup Snapshots' },
    ],
  },
];

/* ----------  ---------- */
const VIEW_LOADERS = {
  login: () => import('./views/auth-login.js?v=2.11'),
  register: () => import('./views/auth-register.js?v=2.11'),
  'forgot-password': () => import('./views/auth-forgot.js?v=2.5'),
  'reset-password': () => import('./views/auth-reset.js?v=2.5'),
  invite: () => import('./views/auth-invite.js?v=2.5'),
  onboarding: () => import('./views/onboarding.js?v=2.6'),
  overview: () => import('./views/overview.js?v=2.7'),
  engines: () => import('./views/engines.js?v=2.6'),
  channels: () => import('./views/channels.js?v=2.6'),
  competitors: () => import('./views/competitors.js?v=2.6'),
  siteaudit: () => import('./views/siteaudit.js?v=2.6'),
  gaps: () => import('./views/gaps.js?v=2.5'),
  questions: () => import('./views/questions.js?v=2.5'),
  facts: () => import('./views/facts.js?v=2.7'),
  plan: () => import('./views/plan.js?v=2.5'),
  workbench: () => import('./views/workbench.js?v=2.6'),
  assets: () => import('./views/assets.js?v=2.6'),
  outreach: () => import('./views/outreach.js?v=2.5'),
  publishing: () => import('./views/publishing.js?v=2.5'),
  verify: () => import('./views/verify.js?v=2.5'),
  report: () => import('./views/report.js?v=2.6'),
  branding: () => import('./views/branding.js?v=2.5'),
  'project-settings': () => import('./views/project-settings.js?v=2.5'),
  'engine-settings': () => import('./views/engine-settings.js?v=2.8'),
  automation: () => import('./views/automation.js?v=2.5'),
  team: () => import('./views/team.js?v=2.5'),
  billing: () => import('./views/billing.js?v=2.8'),
  security: () => import('./views/security.js?v=2.5'),
  archive: () => import('./views/archive.js?v=2.5'),
};

const PUBLIC_ROUTES = ['login', 'register', 'forgot-password', 'reset-password', 'invite'];
const AUTH_ENTRY_ROUTES = new Set(['login', 'register']);
let renderSequence = 0;
let currentView = null;

function cleanupCurrentView() {
  if (currentView && typeof currentView.cleanup === 'function') currentView.cleanup();
  currentView = null;
}

function projectKey(project) {
  if (!project) return '';
  return String(project.id ?? project.slug ?? '');
}

function findProject(projects, id) {
  const key = String(id ?? '');
  return projects.find((project) => projectKey(project) === key || String(project.slug ?? '') === key) || null;
}

/* ----------  ---------- */
class AppState {
  constructor() {
    this.user = null;
    this.tenant = null;
    this.projectsList = [];
    this.activeProjectId = null;
    this.activeJob = null;
    this.currentRoute = 'overview';
    this.currentParams = {};
    this.currentTrack = 'overview';
    this.isJobPolling = false;
    this.sessionChecked = false;
  }

  clearSession() {
    this.user = null;
    this.tenant = null;
    this.projectsList = [];
    this.activeProjectId = null;
    this.activeJob = null;
    this.sessionChecked = true;
  }

  async initSession() {
    try {
      const me = await auth.getMe();
      this.user = me.user;
      this.tenant = me.tenant;
      await this.loadProjects();
      this.sessionChecked = true;
      return true;
    } catch (e) {
      this.clearSession();
      return false;
    }
  }

  async loadProjects() {
    try {
      const list = await projects.list();
      this.projectsList = Array.isArray(list) ? list : (list && list.projects) || [];
      if (!this.activeProjectId && this.projectsList.length > 0) {
        const savedId = localStorage.getItem('citeaura_active_project');
        const found = findProject(this.projectsList, savedId);
        this.activeProjectId = projectKey(found || this.projectsList[0]);
      } else if (this.activeProjectId && !findProject(this.projectsList, this.activeProjectId)) {
        this.activeProjectId = this.projectsList.length ? projectKey(this.projectsList[0]) : null;
      }
    } catch (e) {
      this.projectsList = [];
    }
  }

  setActiveProject(id) {
    const project = findProject(this.projectsList, id);
    this.activeProjectId = project ? projectKey(project) : null;
    try {
      if (this.activeProjectId) localStorage.setItem('citeaura_active_project', this.activeProjectId);
      else localStorage.removeItem('citeaura_active_project');
    } catch (e) {}
  }
}

const state = new AppState();

/* ----------  ---------- */
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '') || 'overview';
  const [routePart, queryPart] = raw.split('?');
  const params = {};
  if (queryPart) {
    const usp = new URLSearchParams(queryPart);
    for (const [k, v] of usp.entries()) {
      params[k] = v;
    }
  }
  return { route: routePart || 'overview', params };
}

function findTrackForView(viewId) {
  for (const track of TRACKS) {
    if (track.views.some((v) => v.id === viewId)) {
      return track;
    }
  }
  return TRACKS[0];
}

/* ----------  ---------- */
async function renderApp() {
  const renderId = ++renderSequence;
  cleanupCurrentView();
  const { route, params } = parseHash();
  state.currentRoute = route;
  state.currentParams = params;

  // 
  const isPublic = PUBLIC_ROUTES.includes(route);
  if (!state.sessionChecked) {
    await state.initSession();
    if (renderId !== renderSequence) return;
  }
  if (AUTH_ENTRY_ROUTES.has(route) && state.user) {
    location.hash = '#/overview';
    return;
  }
  if (!isPublic && !state.user) {
    location.hash = '#/login';
    return;
  }

  const appRoot = document.getElementById('app');
  if (!appRoot) return;

  if (isPublic) {
    stopJobPolling();
    // 
    const loader = VIEW_LOADERS[route];
    if (loader) {
      const module = await loader();
      if (renderId !== renderSequence) return;
      const view = module.default;
      currentView = view;
      const html = typeof view.render === 'function' ? await view.render(createContext()) : '';
      if (renderId !== renderSequence) return;
      setSafeHtml(appRoot, html);
      if (typeof view.mounted === 'function') view.mounted(createContext());
    }
    return;
  }

  // 
  state.currentTrack = findTrackForView(route).id;
  setSafeHtml(appRoot, renderAppShell());
  bindAppShellEvents();

  // 
  const viewContainer = document.getElementById('view-mount');
  if (viewContainer) {
    const loader = VIEW_LOADERS[route] || VIEW_LOADERS.overview;
    try {
      const module = await loader();
      if (renderId !== renderSequence) return;
      const view = module.default;
      currentView = view;
      const context = createContext();
      const html = typeof view.render === 'function' ? await view.render(context) : '';
      if (renderId !== renderSequence || context.activeProjectId !== state.activeProjectId) return;
      setSafeHtml(viewContainer, html);
      if (typeof view.mounted === 'function') view.mounted(createContext());
    } catch (err) {
      if (renderId !== renderSequence) return;
      console.error('Failed to mount view:', err);
      setSafeHtml(viewContainer, `<div class="app-view-container"><div class="banner bad">Error loading view: ${err.message}</div></div>`);
    }
  }

  startJobPolling();
}

function createContext() {
  return {
    state,
    user: state.user,
    tenant: state.tenant,
    projects: state.projectsList,
    activeProjectId: state.activeProjectId,
    params: state.currentParams,
    navigate: (hash) => {
      location.hash = hash;
    },
    reloadSession: async () => {
      const ok = await state.initSession();
      if (!ok) {
        throw {
          error: 'session_establishment_failed',
          detail: 'Sign-in succeeded, but the browser session could not be established. Please try again.',
        };
      }
      return true;
    },
    reloadProjects: async () => {
      await state.loadProjects();
    },
    reloadCurrentView: async () => {
      await renderApp();
    },
    setActiveProject: (id) => {
      state.setActiveProject(id);
    },
    pollActiveJobs: () => {
      checkJobs();
    },
    openTelemetry: (jobId, actionName, options = {}) => {
      openTelemetryModal({
        projectId: options.projectId || state.activeProjectId,
        jobId,
        actionName: actionName || 'Pipeline Execution',
        onClose: options.onClose,
        onComplete: options.onComplete,
      });
    },
  };
}

function renderAppShell() {
  const currentTrackObj = TRACKS.find((t) => t.id === state.currentTrack) || TRACKS[0];
  const activeProj = findProject(state.projectsList, state.activeProjectId);

  return `
    <div class="app-layout">
      <!-- 1.  (Rail) -->
      <aside class="app-rail">
        <div class="rail-top">
          <a class="rail-brand" href="/" title="CiteAura — ${t('common.back_to_home', {}, 'Return to Homepage')}">
            <span class="brand-mark"></span>
          </a>

          <nav class="rail-nav">
            ${TRACKS.map((track) => {
              const isActive = track.id === state.currentTrack;
              return `
                <a href="#/${track.defaultView}" class="rail-btn ${isActive ? 'is-active' : ''}" data-track="${track.id}" title="${t(track.labelKey, {}, track.defaultLabel)}">
                  <span class="rail-icon">
                    <img src="/site-assets/icons/${track.icon}.svg" width="18" height="18" alt="" style="filter: ${isActive ? 'none' : 'grayscale(1) opacity(0.7)'}">
                  </span>
                  <span class="rail-label">${t(track.labelKey, {}, track.defaultLabel)}</span>
                </a>
              `;
            }).join('')}
          </nav>
        </div>

        <div class="rail-bottom">
          <button type="button" class="theme-toggle" id="app-theme-btn" title="Toggle Theme">
            <svg class="icon-sun" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>
            <svg class="icon-moon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          </button>
        </div>
      </aside>

      <!-- 2.  (Sub-Nav) -->
      <aside class="app-subnav" id="app-subnav">
        <div class="subnav-head" style="flex-direction:column;align-items:flex-start;gap:var(--sp-1);padding:var(--sp-4) var(--sp-4) var(--sp-3);border-bottom:1px solid var(--glass-border);">
          <a href="/" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;" title="CiteAura — Return to Homepage">
            <span style="font-family:var(--font-display);font-size:16px;font-weight:800;letter-spacing:-0.03em;color:var(--ink);">CiteAura</span>
            <span class="tag tag-dim" style="font-size:9.5px;padding:1px 5px;border-radius:4px;font-weight:700;letter-spacing:0.06em;color:var(--brand);background:color-mix(in oklch, var(--brand) 12%, transparent);">GEO</span>
          </a>
          <span class="subnav-title" style="margin-top:2px;">${t(currentTrackObj.labelKey, {}, currentTrackObj.defaultLabel)}</span>
        </div>
        <div class="subnav-list">
          ${currentTrackObj.views.map((v) => {
            const isViewActive = v.id === state.currentRoute;
            return `
              <a href="#/${v.id}" class="subnav-item ${isViewActive ? 'is-active' : ''}">
                <span>${t(v.labelKey, {}, v.defaultLabel)}</span>
              </a>
            `;
          }).join('')}
        </div>
      </aside>

      <!-- 3.  -->
      <div class="app-main">
        <header class="app-header">
          <div class="header-left">
            <!--  -->
            <div class="project-switcher">
              <button type="button" class="project-selector-btn" id="project-dropdown-btn">
                <span style="font-weight:700;">${activeProj ? (activeProj.name || activeProj.slug) : 'Select Brand'}</span>
                ${activeProj && activeProj.url ? `<span class="domain-hint">${activeProj.url.replace(/^https?:\/\//, '')}</span>` : ''}
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
              </button>

              <div class="project-dropdown" id="project-dropdown-menu" style="display:none;">
                ${state.projectsList.map((p) => {
                  const isCurrent = projectKey(p) === state.activeProjectId;
                  return `
                    <div class="project-opt ${isCurrent ? 'is-active' : ''}" data-project-id="${projectKey(p)}">
                      <div class="project-opt-meta">
                        <span class="project-opt-name">${p.name || p.slug}</span>
                        <span class="project-opt-url">${p.url || ''}</span>
                      </div>
                      ${isCurrent ? '✓' : ''}
                    </div>
                  `;
                }).join('')}
                <div class="project-dropdown-divider"></div>
                <a href="#/onboarding" class="project-add-btn" style="text-decoration:none;">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                  <span>${t('nav.add_brand', {}, 'Add Brand')}</span>
                </a>
              </div>
            </div>

            <!--  -->
            <div id="active-job-indicator" style="display:none;"></div>
          </div>

          <div class="header-right">
            <!-- Docs / Help Guide -->
            <a href="/docs" target="_blank" rel="noopener noreferrer" class="btn btn-ghost btn-sm" style="display:flex;align-items:center;gap:6px;text-decoration:none;font-weight:600;color:var(--ink-2);" title="Open Documentation & Getting Started Guide">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <span>Docs</span>
            </a>

            <!-- User Menu -->
            <div class="user-menu">
              <button type="button" class="user-menu-btn" id="user-menu-btn">
                <span class="user-avatar">${(state.user?.email || 'U')[0].toUpperCase()}</span>
                <span style="font-weight:600;font-size:var(--fs-2);">${state.user?.email || 'User'}</span>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
              </button>

              <div class="user-dropdown" id="user-dropdown-menu" style="display:none;">
                <div class="user-dropdown-info">
                  <div class="user-dropdown-email">${state.user?.email || ''}</div>
                  <div class="user-dropdown-tenant">${state.tenant?.name || 'Personal Workspace'} · ${state.tenant?.plan || 'trial'}</div>
                </div>
                <a href="#/team" class="user-dropdown-item">${t('nav.team', {}, 'Team & Members')}</a>
                <a href="#/billing" class="user-dropdown-item">${t('nav.billing', {}, 'Subscription & Billing')}</a>
                <div class="project-dropdown-divider"></div>
                <button type="button" class="user-dropdown-item is-danger" id="btn-app-logout" style="width:100%;">
                  ${t('auth.logout', {}, 'Sign Out')}
                </button>
              </div>
            </div>
          </div>
        </header>

        <!--  -->
        <main class="app-main" id="view-mount" style="overflow-y:auto;"></main>
      </div>
    </div>
  `;
}

function bindAppShellEvents() {
  // 
  const projBtn = document.getElementById('project-dropdown-btn');
  const projMenu = document.getElementById('project-dropdown-menu');
  if (projBtn && projMenu) {
    projBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      projMenu.style.display = projMenu.style.display === 'none' ? 'flex' : 'none';
    });
    projMenu.querySelectorAll('.project-opt').forEach((opt) => {
      opt.addEventListener('click', () => {
        const pId = opt.getAttribute('data-project-id');
        if (pId) {
          state.setActiveProject(pId);
          projMenu.style.display = 'none';
          renderApp();
        }
      });
    });
  }

  // 
  const userBtn = document.getElementById('user-menu-btn');
  const userMenu = document.getElementById('user-dropdown-menu');
  if (userBtn && userMenu) {
    userBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      userMenu.style.display = userMenu.style.display === 'none' ? 'flex' : 'none';
    });
  }

  // 
  document.getElementById('btn-app-logout')?.addEventListener('click', async () => {
    try {
      await auth.logout();
    } catch (e) {}
    state.clearSession();
    stopJobPolling();
    toast.success('Signed out');
    location.hash = '#/login';
  });

  // 
  document.getElementById('app-theme-btn')?.addEventListener('click', () => {
    const isDark = document.documentElement.dataset.theme === 'dark';
    const nextTheme = isDark ? 'light' : 'dark';
    document.documentElement.dataset.theme = nextTheme;
    try {
      localStorage.setItem('utheme', nextTheme);
    } catch (e) {}
  });
}

/* ----------  ---------- */
let lastJobStatus = null;
let lastJobId = null;
let jobPollingTimer = null;

async function checkJobs() {
  if (!state.activeProjectId || !state.user) return;
  try {
    const jobs = await projects.getJobs(state.activeProjectId);
    const active = Array.isArray(jobs) ? jobs.find((j) => j.status === 'running' || j.status === 'queued') : null;
    const indicator = document.getElementById('active-job-indicator');

    if (active) {
      state.activeJob = active;
      if (indicator) {
        indicator.style.display = 'inline-flex';
        const actionLabel = active.action || 'Job';
        const stageLabel = active.stage || (active.status === 'running' ? 'executing' : 'queued');
        const progressVal = active.progress || (active.status === 'running' ? 45 : 10);
        setSafeHtml(indicator, `
          <div class="active-job-capsule" id="header-job-capsule" title="Click to view live execution logs & telemetry">
            <div class="job-capsule-content">
              <span class="job-spinner"></span>
              <span class="job-action-label">${actionLabel}</span>
              <span class="job-stage-badge">${stageLabel}</span>
              <span class="job-pct-badge">${progressVal}%</span>
            </div>
            <div class="job-capsule-bar">
              <div class="job-capsule-fill" style="width: ${progressVal}%;"></div>
            </div>
          </div>
        `);
        document.getElementById('header-job-capsule')?.addEventListener('click', () => {
          openTelemetryModal({
            projectId: state.activeProjectId,
            jobId: active.id,
            actionName: active.action,
          });
        });
      }
      lastJobStatus = active.status;
      lastJobId = active.id;
    } else {
      if (state.activeJob && (lastJobStatus === 'running' || lastJobStatus === 'queued')) {
        const finished = jobs.find((job) => job.id === lastJobId);
        if (finished?.status === 'done') toast.success('Pipeline task completed successfully!');
        else if (finished?.status === 'failed') toast.error(finished.error || 'Pipeline task failed');
        renderApp();
      }
      state.activeJob = null;
      lastJobStatus = null;
      lastJobId = null;
      if (indicator) indicator.style.display = 'none';
    }
  } catch (e) {}
}

function startJobPolling() {
  if (jobPollingTimer !== null) return;
  state.isJobPolling = true;
  jobPollingTimer = window.setInterval(checkJobs, 2500);
}

function stopJobPolling() {
  if (jobPollingTimer !== null) {
    window.clearInterval(jobPollingTimer);
    jobPollingTimer = null;
  }
  state.isJobPolling = false;
  state.activeJob = null;
  lastJobStatus = null;
  lastJobId = null;
}

document.addEventListener('click', () => {
  document.getElementById('project-dropdown-menu')?.style.setProperty('display', 'none');
  document.getElementById('user-dropdown-menu')?.style.setProperty('display', 'none');
});

/* ----------  ---------- */
async function init() {
  normalizeLegacyAuthLink();
  await loadCatalogs();

  onAuthFailure(() => {
    state.clearSession();
    stopJobPolling();
    if (!PUBLIC_ROUTES.includes(parseHash().route)) location.hash = '#/login';
  });

  window.addEventListener('hashchange', renderApp);
  renderApp();
}

const INTENT_PLAN_KEY = 'citeaura_intent_plan';
const ENTRY_PLANS = new Set(['starter', 'pro', 'agency', 'enterprise']);

function normalizeLegacyAuthLink() {
  const params = new URLSearchParams(location.search);
  const resetToken = params.get('reset_token');
  const inviteToken = params.get('invite');
  const authRoute = String(params.get('auth') || '').toLowerCase();
  const plan = String(params.get('plan') || '').toLowerCase();
  const billing = String(params.get('billing') || '').toLowerCase();

  if (resetToken || inviteToken) {
    const route = resetToken ? 'reset-password' : 'invite';
    const token = resetToken || inviteToken;
    history.replaceState(null, '', `${location.pathname}#/${route}?token=${encodeURIComponent(token)}`);
    return;
  }

  // 认证入口使用 query 作为 fragment 的兼容路径，避免外部重定向或分享工具丢失 hash。
  if (authRoute === 'login' || authRoute === 'register') {
    history.replaceState(null, '', `${location.pathname}#/${authRoute}`);
    return;
  }

  // 落地页「Subscribe Pro」等：保留升级意图，登录后可立刻结账，不必等试用结束。
  if (ENTRY_PLANS.has(plan)) {
    try {
      sessionStorage.setItem(INTENT_PLAN_KEY, plan);
    } catch (e) {}
    history.replaceState(null, '', `${location.pathname}#/billing?plan=${encodeURIComponent(plan)}`);
    return;
  }

  if (billing === 'success' || billing === 'canceled') {
    history.replaceState(null, '', `${location.pathname}#/billing?billing=${encodeURIComponent(billing)}`);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
