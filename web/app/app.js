/**
 * CiteAura 
 */

import { auth, projects, onAuthFailure } from './api.js';
import { t, loadCatalogs, getLocale, setLocale } from './i18n.js';
import { toast } from './components/toast.js';
import { setSafeHtml } from './safe-html.js';
import { openTelemetryModal } from './components/telemetry-modal.js';

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
      { id: 'assets', labelKey: 'nav.assets', defaultLabel: 'Deployable Assets' },
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
      { id: 'integrations', labelKey: 'nav.integrations', defaultLabel: 'SEO Integrations' },
      { id: 'team', labelKey: 'nav.team', defaultLabel: 'Team Members' },
      { id: 'billing', labelKey: 'nav.billing', defaultLabel: 'Billing & Plans' },
      { id: 'security', labelKey: 'nav.security', defaultLabel: 'Enterprise Security' },
      { id: 'archive', labelKey: 'nav.archive', defaultLabel: 'Backup Snapshots' },
    ],
  },
];

/* ----------  ---------- */
const VIEW_LOADERS = {
  login: () => import('./views/auth-login.js?v=2.5'),
  register: () => import('./views/auth-register.js?v=2.5'),
  'forgot-password': () => import('./views/auth-forgot.js?v=2.5'),
  'reset-password': () => import('./views/auth-reset.js?v=2.5'),
  invite: () => import('./views/auth-invite.js?v=2.5'),
  onboarding: () => import('./views/onboarding.js?v=2.5'),
  overview: () => import('./views/overview.js?v=2.5'),
  engines: () => import('./views/engines.js?v=2.5'),
  channels: () => import('./views/channels.js?v=2.5'),
  competitors: () => import('./views/competitors.js?v=2.5'),
  siteaudit: () => import('./views/siteaudit.js?v=2.5'),
  gaps: () => import('./views/gaps.js?v=2.5'),
  questions: () => import('./views/questions.js?v=2.5'),
  facts: () => import('./views/facts.js?v=2.5'),
  plan: () => import('./views/plan.js?v=2.5'),
  workbench: () => import('./views/workbench.js?v=2.5'),
  assets: () => import('./views/assets.js?v=2.5'),
  outreach: () => import('./views/outreach.js?v=2.5'),
  publishing: () => import('./views/publishing.js?v=2.5'),
  verify: () => import('./views/verify.js?v=2.5'),
  report: () => import('./views/report.js?v=2.5'),
  branding: () => import('./views/branding.js?v=2.5'),
  'project-settings': () => import('./views/project-settings.js?v=2.5'),
  'engine-settings': () => import('./views/engine-settings.js?v=2.5'),
  automation: () => import('./views/automation.js?v=2.5'),
  integrations: () => import('./views/integrations.js?v=2.5'),
  team: () => import('./views/team.js?v=2.5'),
  billing: () => import('./views/billing.js?v=2.5'),
  security: () => import('./views/security.js?v=2.5'),
  archive: () => import('./views/archive.js?v=2.5'),
};

const PUBLIC_ROUTES = ['login', 'register', 'forgot-password', 'reset-password', 'invite'];

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
  }

  async initSession() {
    try {
      const me = await auth.getMe();
      this.user = me.user;
      this.tenant = me.tenant;
      await this.loadProjects();
      return true;
    } catch (e) {
      this.user = null;
      this.tenant = null;
      return false;
    }
  }

  async loadProjects() {
    try {
      const list = await projects.list();
      this.projectsList = Array.isArray(list) ? list : (list && list.projects) || [];
      if (!this.activeProjectId && this.projectsList.length > 0) {
        const savedId = localStorage.getItem('citeaura_active_project');
        const found = this.projectsList.find((p) => p.id === savedId || p.slug === savedId);
        this.activeProjectId = found ? (found.id || found.slug) : (this.projectsList[0].id || this.projectsList[0].slug);
      }
    } catch (e) {
      this.projectsList = [];
    }
  }

  setActiveProject(id) {
    this.activeProjectId = id;
    try {
      localStorage.setItem('citeaura_active_project', id);
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
  const { route, params } = parseHash();
  state.currentRoute = route;
  state.currentParams = params;

  // 
  const isPublic = PUBLIC_ROUTES.includes(route);
  if (!isPublic && !state.user) {
    const ok = await state.initSession();
    if (!ok) {
      location.hash = '#/login';
      return;
    }
  }

  const appRoot = document.getElementById('app');
  if (!appRoot) return;

  if (isPublic) {
    // 
    const loader = VIEW_LOADERS[route];
    if (loader) {
      const module = await loader();
      const view = module.default;
      setSafeHtml(appRoot, typeof view.render === 'function' ? await view.render(createContext()) : '');
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
      const view = module.default;
      setSafeHtml(viewContainer, typeof view.render === 'function' ? await view.render(createContext()) : '');
      if (typeof view.mounted === 'function') view.mounted(createContext());
    } catch (err) {
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
      await state.initSession();
    },
    reloadProjects: async () => {
      await state.loadProjects();
    },
    setActiveProject: (id) => {
      state.setActiveProject(id);
    },
    pollActiveJobs: () => {
      checkJobs();
    },
    openTelemetry: (jobId, actionName) => {
      openTelemetryModal({
        projectId: state.activeProjectId,
        jobId,
        actionName: actionName || 'Pipeline Execution',
      });
    },
  };
}

function renderAppShell() {
  const currentTrackObj = TRACKS.find((t) => t.id === state.currentTrack) || TRACKS[0];
  const activeProj = state.projectsList.find((p) => p.id === state.activeProjectId || p.slug === state.activeProjectId) || state.projectsList[0];

  return `
    <div class="app-layout">
      <!-- 1.  (Rail) -->
      <aside class="app-rail">
        <div class="rail-top">
          <a class="rail-brand" href="/" title="${t('common.back_to_home', {}, 'Return to Homepage')}">
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
        <div class="subnav-head">
          <span class="subnav-title">${t(currentTrackObj.labelKey, {}, currentTrackObj.defaultLabel)}</span>
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
                  const isCurrent = (p.id || p.slug) === (state.activeProjectId);
                  return `
                    <div class="project-opt ${isCurrent ? 'is-active' : ''}" data-project-id="${p.id || p.slug}">
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

            <!-- Language Indicator -->
            <div class="lang-switch" role="group" aria-label="Language">
              <button type="button" data-lang="en" class="lang-btn is-active" aria-pressed="true">EN</button>
            </div>

            <!--  -->
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

  document.addEventListener('click', () => {
    if (projMenu) projMenu.style.display = 'none';
    if (userMenu) userMenu.style.display = 'none';
  });

  // 
  document.getElementById('btn-app-logout')?.addEventListener('click', async () => {
    try {
      await auth.logout();
    } catch (e) {}
    state.user = null;
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

  // 
  document.querySelectorAll('.lang-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const l = btn.getAttribute('data-lang');
      if (l) {
        await setLocale(l);
        renderApp();
      }
    });
  });
}

/* ----------  ---------- */
let lastJobStatus = null;

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
    } else {
      if (state.activeJob && (lastJobStatus === 'running' || lastJobStatus === 'queued')) {
        toast.success(`Pipeline task completed successfully!`);
        renderApp();
      }
      state.activeJob = null;
      lastJobStatus = null;
      if (indicator) indicator.style.display = 'none';
    }
  } catch (e) {}
}

function startJobPolling() {
  if (state.isJobPolling) return;
  state.isJobPolling = true;
  setInterval(checkJobs, 2500);
}

/* ----------  ---------- */
async function init() {
  normalizeLegacyAuthLink();
  await loadCatalogs();

  onAuthFailure(() => {
    location.hash = '#/login';
  });

  window.addEventListener('hashchange', renderApp);
  renderApp();
}

function normalizeLegacyAuthLink() {
  const params = new URLSearchParams(location.search);
  const resetToken = params.get('reset_token');
  const inviteToken = params.get('invite');
  if (!resetToken && !inviteToken) return;
  const route = resetToken ? 'reset-password' : 'invite';
  const token = resetToken || inviteToken;
  history.replaceState(null, '', `${location.pathname}#/${route}?token=${encodeURIComponent(token)}`);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
